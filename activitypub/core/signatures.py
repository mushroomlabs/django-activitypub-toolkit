import base64
from dataclasses import asdict, dataclass
from enum import StrEnum

from .exceptions import InvalidSignature


class HttpSignatureAlgorithms(StrEnum):
    RSA_SHA56 = "rsa-sha256"
    HIDDEN = "hs2019"


@dataclass
class HttpSignature:
    algorithm: str
    headers: list[str]
    signature: bytes
    key_id: str

    def serialize(self):
        return asdict(self)

    @classmethod
    def load(cls, header_data):
        bits = {}
        for item in header_data.split(","):
            name, value = item.split("=", 1)
            value = value.strip('"')
            bits[name.lower()] = value
        try:
            algorithm = HttpSignatureAlgorithms(bits["algorithm"])
            return cls(
                algorithm=algorithm,
                headers=bits["headers"].split(),
                signature=base64.b64decode(bits["signature"]),
                key_id=bits["keyid"],
            )
        except ValueError:
            raise InvalidSignature(f"algorithm provided is not supported: {algorithm}")
        except KeyError as e:
            key_names = " ".join(bits.keys())
            raise InvalidSignature(f"Missing item from details (have: {key_names}, error: {e})")

    def header_payload(self, request):
        headers = {}
        for header_name in self.headers:
            if header_name == "(request-target)":
                value = f"{request.method.lower()} {request.path}"
            elif header_name == "content-type":
                value = request.headers["content-type"]
            elif header_name == "content-length":
                value = request.headers["content-length"]
            else:
                value = request.META["HTTP_%s" % header_name.upper().replace("-", "_")]
            headers[header_name] = value
        return "\n".join(f"{name.lower()}: {value}" for name, value in headers.items())
