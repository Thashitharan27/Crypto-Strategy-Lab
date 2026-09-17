"""Hardened ChatGPT connection facade.

The original implementation is kept in ``chatgpt_connection_impl``.  This
facade makes process state authoritative once the GUI owns the MCP/tunnel
children, so a short localhost TCP-probe miss cannot falsely label a busy MCP
process as stopped.
"""
from __future__ import annotations

from . import chatgpt_connection_impl as _impl

# Preserve the existing public surface, including helpers used by tests and the
# main window.  Dunder names stay local to this facade.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

MCP_STARTUP_PROBE_TIMEOUT_SECONDS = 0.25


class ChatGPTConnectionManager(_impl.ChatGPTConnectionManager):
    """Connection manager that distinguishes process death from temporary load."""

    def _reachable(self):
        try:
            with socket.create_connection(
                ("127.0.0.1", self.port),
                timeout=MCP_STARTUP_PROBE_TIMEOUT_SECONDS,
            ):
                return True
        except OSError:
            return False

    def _emit(self):
        # Once this GUI owns the MCP child, QProcess is the authoritative source
        # for Running/Stopped.  Socket probes are still useful before startup to
        # detect an externally occupied port, but not as a liveness verdict for
        # a process that may be busy serving a long walk-forward request.
        if self._mcp_started and self.mcp.state() == QProcess.Starting:
            mcp = "Starting"
        elif self._mcp_started and self.mcp.state() == QProcess.Running:
            mcp = "Running"
        else:
            mcp = "Port in use" if self._reachable() else "Stopped"
        tunnel = "Running" if self.tunnel.state() == QProcess.Running else "Stopped"
        self.state_changed.emit(self.state, mcp, tunnel)

    def _poll(self):
        if self._stopping:
            return

        # Keep the original startup handshake: the MCP must actually accept a
        # localhost connection before the tunnel is launched.
        if self._starting:
            return super()._poll()

        if self.state == "Connected":
            mcp_alive = (
                self._mcp_started and self.mcp.state() == QProcess.Running
            )
            tunnel_alive = (
                self._tunnel_started and self.tunnel.state() == QProcess.Running
            )
            if not mcp_alive:
                self.state = "Error"
                self._set_diagnostic(
                    "Connection health check failed: the local MCP process stopped."
                )
            elif not tunnel_alive:
                self.state = "Error"
                self._set_diagnostic(
                    "Connection health check failed: the secure tunnel process stopped."
                )

        self._emit()


# ChatGPTIntegrationWidget is defined in the implementation module and resolves
# ChatGPTConnectionManager from that module's globals when instantiated.  Patch
# that binding before any widget is created.
_impl.ChatGPTConnectionManager = ChatGPTConnectionManager
globals()["ChatGPTConnectionManager"] = ChatGPTConnectionManager
ChatGPTIntegrationWidget = _impl.ChatGPTIntegrationWidget
