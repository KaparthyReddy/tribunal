from dataclasses import dataclass

from tribunal.config import Settings


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class SandboxPolicy:
    image: str
    timeout_s: int = 120
    memory: str = "512m"
    cpus: float = 1.0
    pids_limit: int = 256
    max_output_bytes: int = 65536
    tmpfs_size: str = "256m"
    require_digest: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxPolicy":
        return cls(
            image=settings.sandbox_image,
            timeout_s=settings.sandbox_timeout_s,
            memory=settings.sandbox_memory,
            cpus=settings.sandbox_cpus,
            pids_limit=settings.sandbox_pids_limit,
            max_output_bytes=settings.sandbox_max_output_bytes,
            require_digest=settings.sandbox_require_digest,
        )

    def validate(self) -> None:
        if not self.image:
            raise PolicyError("sandbox image must not be empty")
        if self.require_digest and "@sha256:" not in self.image:
            raise PolicyError("sandbox image must be pinned by digest (name@sha256:...)")
        if self.timeout_s <= 0:
            raise PolicyError("timeout_s must be positive")
        if self.cpus <= 0:
            raise PolicyError("cpus must be positive")
        if self.pids_limit <= 0:
            raise PolicyError("pids_limit must be positive")
        if self.max_output_bytes < 1024:
            raise PolicyError("max_output_bytes must be at least 1024")
