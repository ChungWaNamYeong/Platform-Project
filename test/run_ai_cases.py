#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量执行 AI 问答用例并导出回答、引用与统计指标。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_BASE_URL = "https://cloud.fastgpt.io/api"
GENERAL_REJECT_HINTS = [
    "不在知识库",
    "非课程",
    "无法确认",
    "无法查询",
    "无法获取",
    "无法确定",
    "不提供",
    "不能提供",
    "拒绝",
    "安全",
    "合规",
]
REQUIRED_CITATION_TYPES = {"领域内", "对抗"}


@dataclass
class CaseResult:
    case_id: str
    case_type: str
    question: str
    expected: str
    answer_text: str
    citations: list[dict[str, Any]]
    has_citation: bool
    passed: bool
    is_reject: bool
    rule_reason: str
    error: str
    latency_ms: int
    raw_response_excerpt: str


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text or "")
    return cleaned.lower()


def _contains_any(answer: str, keywords: list[str]) -> bool:
    if not keywords:
        return False
    normalized_answer = _normalize_text(answer)
    return any(_normalize_text(k) in normalized_answer for k in keywords if k)


def _build_chat_completions_url(base_url: str) -> str:
    b = base_url.strip().rstrip("/")
    if not b:
        raise ValueError("base_url 不能为空。")

    lowered = b.lower()
    if lowered.endswith("/chat/completions"):
        return b
    if lowered.endswith("/api/v1"):
        return f"{b}/chat/completions"
    if lowered.endswith("/v1"):
        return f"{b}/chat/completions"
    if lowered.endswith("/api"):
        return f"{b}/v1/chat/completions"
    return f"{b}/api/v1/chat/completions"


def _extract_answer(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(content).strip() if isinstance(content, str) else ""


def _extract_citations(data: dict[str, Any]) -> list[dict[str, Any]]:
    response_data = data.get("responseData")
    if not isinstance(response_data, list):
        return []

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for module in response_data:
        if not isinstance(module, dict):
            continue
        quote_list = module.get("quoteList")
        if not isinstance(quote_list, list):
            continue
        for quote in quote_list:
            if not isinstance(quote, dict):
                continue
            quote_id = str(quote.get("id", "")).strip()
            if quote_id and quote_id in seen:
                continue
            if quote_id:
                seen.add(quote_id)
            refs.append(
                {
                    "id": quote_id,
                    "q": str(quote.get("q", "")).strip(),
                    "a": str(quote.get("a", "")).strip(),
                    "source": str(quote.get("source", "")).strip(),
                    "sourceName": str(quote.get("sourceName", "")).strip(),
                    "datasetId": str(quote.get("datasetId", "")).strip(),
                }
            )
    return refs


class TLSHttpAdapter(requests.adapters.HTTPAdapter):
    """支持自定义 TLS 最低版本与可选证书校验。"""

    def __init__(self, *, ssl_context: ssl.SSLContext, **kwargs: Any) -> None:
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(*args, **kwargs)


def _build_session(*, trust_env_proxy: bool, insecure: bool, tls_min_version: str) -> requests.Session:
    session = requests.Session()
    # 某些 Windows/VPN 环境会注入系统代理，导致 TLS 代理握手 EOF；默认关闭更稳。
    session.trust_env = bool(trust_env_proxy)

    ctx = ssl.create_default_context()
    min_map = {
        "1.2": ssl.TLSVersion.TLSv1_2,
        "1.3": ssl.TLSVersion.TLSv1_3,
    }
    ctx.minimum_version = min_map[tls_min_version]
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    adapter = TLSHttpAdapter(ssl_context=ctx, max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", requests.adapters.HTTPAdapter(max_retries=0))
    return session


def _run_single_case(
    case: dict[str, Any],
    *,
    session: requests.Session,
    api_url: str,
    api_key: str,
    timeout: int,
    max_retries: int,
    chat_id: str,
    dry_run: bool,
    insecure: bool,
) -> CaseResult:
    case_id = str(case.get("id", "")).strip()
    case_type = str(case.get("type", "")).strip()
    question = str(case.get("question", "")).strip()
    expected = str(case.get("expected", "")).strip()
    keywords_any = list(case.get("keywords_any") or [])
    reject_hints_any = list(case.get("reject_hints_any") or [])

    if dry_run:
        answer = "DRY RUN: 未实际请求 API。"
        citations: list[dict[str, Any]] = []
        passed, is_reject, reason = _judge_case(
            case_type=case_type,
            answer=answer,
            keywords_any=keywords_any,
            reject_hints_any=reject_hints_any,
        )
        return CaseResult(
            case_id=case_id,
            case_type=case_type,
            question=question,
            expected=expected,
            answer_text=answer,
            citations=citations,
            has_citation=False,
            passed=passed,
            is_reject=is_reject,
            rule_reason=reason,
            error="",
            latency_ms=0,
            raw_response_excerpt="",
        )

    payload: dict[str, Any] = {
        "stream": False,
        "detail": True,
        "messages": [{"role": "user", "content": question}],
    }
    if chat_id:
        payload["chatId"] = chat_id

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error = ""
    started = time.perf_counter()
    for attempt in range(1, max_retries + 2):
        try:
            resp = session.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
                verify=(not insecure),
            )
            resp.raise_for_status()
            data = resp.json()
            answer = _extract_answer(data)
            citations = _extract_citations(data)
            passed, is_reject, reason = _judge_case(
                case_type=case_type,
                answer=answer,
                keywords_any=keywords_any,
                reject_hints_any=reject_hints_any,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return CaseResult(
                case_id=case_id,
                case_type=case_type,
                question=question,
                expected=expected,
                answer_text=answer,
                citations=citations,
                has_citation=bool(citations),
                passed=passed,
                is_reject=is_reject,
                rule_reason=reason,
                error="",
                latency_ms=elapsed_ms,
                raw_response_excerpt=json.dumps(data, ensure_ascii=False)[:1200],
            )
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt <= max_retries:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return CaseResult(
        case_id=case_id,
        case_type=case_type,
        question=question,
        expected=expected,
        answer_text="",
        citations=[],
        has_citation=False,
        passed=False,
        is_reject=False,
        rule_reason="api_error",
        error=last_error or "API 请求失败",
        latency_ms=elapsed_ms,
        raw_response_excerpt="",
    )


def _judge_case(
    *,
    case_type: str,
    answer: str,
    keywords_any: list[str],
    reject_hints_any: list[str],
) -> tuple[bool, bool, str]:
    if case_type == "领域外":
        is_reject = _contains_any(answer, reject_hints_any) or _contains_any(answer, GENERAL_REJECT_HINTS)
        return is_reject, is_reject, "ood_reject" if is_reject else "ood_not_reject"

    matched = _contains_any(answer, keywords_any)
    return matched, False, "keyword_match" if matched else "keyword_miss"


def _to_summary(results: list[CaseResult]) -> dict[str, Any]:
    total = len(results)
    pass_count = sum(1 for r in results if r.passed)
    ood_items = [r for r in results if r.case_type == "领域外"]
    ood_total = len(ood_items)
    ood_reject_count = sum(1 for r in ood_items if r.is_reject)

    citation_count = sum(1 for r in results if r.has_citation)
    citation_hit_rate = (citation_count / total) if total else 0.0

    citation_and_pass_count = sum(1 for r in results if r.has_citation and r.passed)
    context_precision_proxy = (citation_and_pass_count / citation_count) if citation_count else 0.0

    required_items = [r for r in results if r.case_type in REQUIRED_CITATION_TYPES]
    required_total = len(required_items)
    required_citation_and_pass = sum(1 for r in required_items if r.has_citation and r.passed)
    context_recall_proxy = (required_citation_and_pass / required_total) if required_total else 0.0

    return {
        "total_count": total,
        "pass_count": pass_count,
        "pass_rate": round((pass_count / total) if total else 0.0, 6),
        "ood_total": ood_total,
        "ood_reject_count": ood_reject_count,
        "ood_reject_rate": round((ood_reject_count / ood_total) if ood_total else 0.0, 6),
        "citation_hit_count": citation_count,
        "citation_hit_rate": round(citation_hit_rate, 6),
        "context_precision_proxy": round(context_precision_proxy, 6),
        "context_recall_proxy": round(context_recall_proxy, 6),
        "required_citation_scope_types": sorted(REQUIRED_CITATION_TYPES),
        "required_count_for_context_recall": required_total,
        "required_citation_and_pass_count": required_citation_and_pass,
    }


def _write_outputs(output_dir: Path, results: list[CaseResult], summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_json = output_dir / "results.json"
    results_csv = output_dir / "results.csv"
    summary_json = output_dir / "summary.json"

    rows = [
        {
            "id": r.case_id,
            "type": r.case_type,
            "question": r.question,
            "expected": r.expected,
            "answer_text": r.answer_text,
            "citations_count": len(r.citations),
            "citations": json.dumps(r.citations, ensure_ascii=False),
            "has_citation": r.has_citation,
            "pass": r.passed,
            "is_reject": r.is_reject,
            "rule_reason": r.rule_reason,
            "latency_ms": r.latency_ms,
            "error": r.error,
        }
        for r in results
    ]

    with results_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "results": [
                    {
                        "id": r.case_id,
                        "type": r.case_type,
                        "question": r.question,
                        "expected": r.expected,
                        "answer_text": r.answer_text,
                        "citations": r.citations,
                        "has_citation": r.has_citation,
                        "pass": r.passed,
                        "is_reject": r.is_reject,
                        "rule_reason": r.rule_reason,
                        "latency_ms": r.latency_ms,
                        "error": r.error,
                        "raw_response_excerpt": r.raw_response_excerpt,
                    }
                    for r in results
                ],
                "summary": summary,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    if rows:
        with results_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def _load_cases(case_file: Path) -> list[dict[str, Any]]:
    with case_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("用例文件必须是 JSON 数组。")
    return [x for x in data if isinstance(x, dict)]


def _parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="运行 AI 问答自动化测试用例")
    parser.add_argument("--cases-file", default=str(default_root / "ai_test_cases.json"), help="测试用例 JSON 文件路径")
    parser.add_argument("--output-dir", default=str(default_root / "output"), help="输出目录")
    parser.add_argument("--base-url", default=os.getenv("FASTGPT_BASE_URL", DEFAULT_BASE_URL), help="FastGPT Base URL")
    parser.add_argument("--api-key", default=os.getenv("FASTGPT_API_KEY", ""), help="FastGPT API Key")
    parser.add_argument("--chat-id", default="", help="可选 chatId（用于服务端记忆会话）")
    parser.add_argument("--timeout", type=int, default=120, help="单请求超时时间（秒）")
    parser.add_argument("--max-retries", type=int, default=2, help="失败重试次数")
    parser.add_argument("--sleep", type=float, default=0.0, help="每条用例之间休眠秒数")
    parser.add_argument(
        "--trust-env-proxy",
        action="store_true",
        help="允许 requests 使用系统代理环境（默认关闭，避免 TLS 代理握手 EOF）。",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="关闭 TLS 证书校验（仅用于排障，不建议长期使用）。",
    )
    parser.add_argument(
        "--tls-min-version",
        choices=["1.2", "1.3"],
        default="1.2",
        help="TLS 最低版本（默认 1.2）。",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅演练流程，不真实请求 API")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    case_file = Path(args.cases_file)
    output_dir = Path(args.output_dir)
    if not case_file.exists():
        print(f"[ERROR] 用例文件不存在: {case_file}")
        return 1

    if not args.dry_run and not args.api_key.strip():
        print("[ERROR] 缺少 API Key。请通过 --api-key 或环境变量 FASTGPT_API_KEY 提供。")
        return 1

    try:
        api_url = _build_chat_completions_url(args.base_url)
    except ValueError as exc:
        print(f"[ERROR] Base URL 无效: {exc}")
        return 1

    cases = _load_cases(case_file)
    if not cases:
        print("[ERROR] 未读取到有效用例。")
        return 1

    print(f"[INFO] 开始执行 {len(cases)} 条用例")
    print(f"[INFO] API URL: {api_url}")
    print(f"[INFO] 输出目录: {output_dir}")
    print(f"[INFO] trust_env_proxy: {args.trust_env_proxy}")
    print(f"[INFO] tls_min_version: {args.tls_min_version}")
    if args.insecure:
        print("[WARN] 已启用 --insecure（证书校验关闭，仅排障用途）")

    session = _build_session(
        trust_env_proxy=bool(args.trust_env_proxy),
        insecure=bool(args.insecure),
        tls_min_version=str(args.tls_min_version),
    )

    results: list[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id", "")).strip() or f"CASE-{index:02d}"
        print(f"[RUN] ({index}/{len(cases)}) {case_id}")
        result = _run_single_case(
            case,
            session=session,
            api_url=api_url,
            api_key=args.api_key.strip(),
            timeout=int(args.timeout),
            max_retries=max(0, int(args.max_retries)),
            chat_id=str(args.chat_id or "").strip(),
            dry_run=bool(args.dry_run),
            insecure=bool(args.insecure),
        )
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        cite_info = f"citations={len(result.citations)}"
        err_info = f" error={result.error}" if result.error else ""
        print(f"[{status}] {result.case_id} {cite_info}{err_info}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    summary = _to_summary(results)
    _write_outputs(output_dir, results, summary)
    print("[INFO] 统计完成:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
