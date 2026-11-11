"""Generate the versioned gRPC Python types using the pinned compiler."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "contracts/python/traffic_contracts"


if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I{ROOT / 'contracts/v1'}",
                    f"--python_out={TARGET}", f"--grpc_python_out={TARGET}",
                    str(ROOT / "contracts/v1/publisher.proto")], check=True)
    path = TARGET / "publisher_pb2_grpc.py"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "import publisher_pb2 as publisher__pb2", "from . import publisher_pb2 as publisher__pb2"), encoding="utf-8")
    print("Generated publisher protobuf/gRPC types with package-relative imports")
