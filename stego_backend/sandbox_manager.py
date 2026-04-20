"""容器沙箱管理器。"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict, Optional

import docker
from docker.errors import APIError, NotFound


class StegoSandbox:
    """管理实验沙箱容器的启动与销毁。"""

    NETWORK_NAME = "stego_labs_net"
    DEFAULT_IMAGE = "stego-lab:py312"

    def __init__(self) -> None:
        """初始化 Docker 客户端并确保隔离网络可用。"""
        self.client = docker.from_env()
        self._ensure_network()
        self._ensure_sandbox_image()

    def _ensure_network(self) -> None:
        """确保实验容器使用的虚拟网桥存在。"""
        try:
            network = self.client.networks.get(self.NETWORK_NAME)
            attrs = network.attrs or {}
            is_internal = bool(attrs.get("Internal"))
            is_bridge = attrs.get("Driver") == "bridge"
            # 需要发布端口给前端访问，因此不能使用 internal 网络。
            if is_bridge and not is_internal:
                return
            if attrs.get("Containers"):
                raise APIError(f"网络 {self.NETWORK_NAME} 配置不兼容且仍有容器连接，无法自动重建。")
            network.remove()
        except NotFound:
            pass

        # 使用用户自定义 bridge 网络，避免 host 网络模式导致的宿主机网络暴露。
        self.client.networks.create(
            name=self.NETWORK_NAME,
            driver="bridge",
            internal=False,
        )

    def _ensure_sandbox_image(self) -> None:
        """确保实验镜像存在，不存在时自动构建。"""
        try:
            self.client.images.get(self.DEFAULT_IMAGE)
            return
        except NotFound:
            pass

        dockerfile_path = Path(__file__).resolve().parent / "sandbox.Dockerfile"
        self.client.images.build(
            path=str(dockerfile_path.parent),
            dockerfile=dockerfile_path.name,
            tag=self.DEFAULT_IMAGE,
            rm=True,
            pull=True,
        )

    def start_container(
        self,
        image: Optional[str] = None,
        container_port: int = 8501,
        command: Optional[str] = None,
        environment: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        启动实验容器并返回容器 ID 与 Web 映射端口。

        Args:
            image: 容器镜像名，不传则使用默认实验镜像。
            container_port: 容器内 Web 服务端口。
            command: 可选的启动命令。
            environment: 可选环境变量。
            name: 可选容器名。
        """
        selected_image = image or self.DEFAULT_IMAGE
        port_key = f"{container_port}/tcp"
        container = self.client.containers.run(
            image=selected_image,
            command=command,
            environment=environment,
            name=name,
            detach=True,
            network=self.NETWORK_NAME,
            ports={port_key: None},
            mem_limit="512m",
            cpu_period=100000,
            cpu_quota=50000,
            privileged=False,
        )

        host_port: Optional[int] = None
        for _ in range(20):
            container.reload()
            port_bindings = container.attrs["NetworkSettings"]["Ports"].get(port_key) or []
            if port_bindings and port_bindings[0].get("HostPort"):
                host_port = int(port_bindings[0]["HostPort"])
                break
            if container.status in {"exited", "dead"}:
                break
            time.sleep(0.25)

        if host_port is None:
            container.reload()
            container_state = container.attrs.get("State", {})
            status = container_state.get("Status", "unknown")
            error = container_state.get("Error", "")
            logs_text = ""
            try:
                logs_text = container.logs(tail=20).decode("utf-8", errors="ignore").strip()
            except Exception:
                logs_text = ""
            try:
                container.remove(force=True)
            except Exception:
                pass
            raise APIError(
                f"容器 {container.id} 未成功映射端口 {port_key}，状态={status}，"
                f"错误={error or '-'}，日志={logs_text[:300] or '-'}"
            )

        return {
            "container_id": container.id,
            "web_port": host_port,
            "image": selected_image,
        }

    def stop_container(self, container_id: str, remove: bool = True) -> bool:
        """
        停止容器并按需删除。

        Args:
            container_id: 容器 ID。
            remove: 是否在停止后删除容器。
        """
        try:
            container = self.client.containers.get(container_id)
        except NotFound:
            return False

        container.stop()
        if remove:
            container.remove()
        return True
