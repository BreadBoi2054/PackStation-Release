"""Camera Discovery - Find cameras on local network + parse QR codes from camera body."""
import re
import socket
import struct
import threading
import time
from typing import Optional
from dataclasses import dataclass, field
from core.logger import get_logger

log = get_logger()


@dataclass
class CameraInfo:
    """Parsed camera information from QR code or discovery."""
    ip: str = ""
    port: int = 554
    username: str = "admin"
    password: str = ""
    serial: str = ""
    model: str = ""
    brand: str = ""
    rtsp_url: str = ""
    http_port: int = 80

    def build_rtsp_url(self, channel: int = 1, subtype: int = 0) -> str:
        """Build RTSP URL for this camera."""
        if self.rtsp_url:
            return self.rtsp_url
        if not self.ip:
            return ""
        import urllib.parse
        pwd_quoted = urllib.parse.quote(self.password) if self.password else ""
        cred = f"{self.username}:{pwd_quoted}@" if self.password else f"{self.username}@"
        # Dahua/Imou format
        return f"rtsp://{cred}{self.ip}:{self.port}/cam/realmonitor?channel={channel}&subtype={subtype}"



def parse_camera_qr(qr_text: str) -> CameraInfo:
    """
    Parse QR code from camera body. Supports multiple formats:
    - Imou/Dahua: various SN/SC/pwd formats
    - Generic RTSP URL
    - IP:port format
    - JSON format
    """
    info = CameraInfo()
    text = qr_text.strip()

    # Format 1: Direct RTSP URL
    if text.lower().startswith("rtsp://"):
        info.rtsp_url = text
        match = re.search(r"rtsp://(?:([^:@]+):([^@]+)@)?([^:/]+)(?::(\d+))?", text)
        if match:
            info.username = match.group(1) or "admin"
            info.password = match.group(2) or ""
            info.ip = match.group(3) or ""
            info.port = int(match.group(4)) if match.group(4) else 554
        return info

    # Format 2: Imou/Dahua QR - "SN:XXXXX" or "SN=XXXXX"
    sn_match = re.search(r"(?:SN|S/N|sn)[=:\s]+([A-Z0-9]+)", text, re.IGNORECASE)
    if sn_match:
        info.serial = sn_match.group(1)
        info.brand = "Imou/Dahua"

    # Extract password/security code
    pwd_match = re.search(r"(?:SC|PWD|PW|PASS|pwd|Password|password)[=:\s]+([^\s,;]+)", text, re.IGNORECASE)
    if pwd_match:
        info.password = pwd_match.group(1)

    # Extract IP if present
    ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", text)
    if ip_match:
        info.ip = ip_match.group(1)

    # Extract port if present
    port_match = re.search(r"(?:PORT|port)[=:\s]+(\d+)", text, re.IGNORECASE)
    if port_match:
        info.port = int(port_match.group(1))

    # Extract username if present
    user_match = re.search(r"(?:USER|USR|username)[=:\s]+([^\s,;]+)", text, re.IGNORECASE)
    if user_match:
        info.username = user_match.group(1)

    # Format 3: Imou URL format (app deep link)
    if "imou.com" in text or "lechange" in text:
        info.brand = "Imou"
        # Try to extract device ID from URL
        did_match = re.search(r"(?:deviceId|did|device)[=:/]+([A-Z0-9]+)", text, re.IGNORECASE)
        if did_match:
            info.serial = did_match.group(1)

    # Format 4: Simple "IP:PORT" or "IP"
    if not info.serial and not info.ip:
        simple_ip = re.match(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?$", text)
        if simple_ip:
            info.ip = simple_ip.group(1)
            if simple_ip.group(2):
                info.port = int(simple_ip.group(2))

    # Format 5: Key-value pairs separated by comma/semicolon/newline
    for sep in [",", ";", "\n", "&"]:
        if sep in text:
            for part in text.split(sep):
                part = part.strip()
                if "=" in part or ":" in part:
                    k, _, v = part.partition("=" if "=" in part else ":")
                    k, v = k.strip().upper(), v.strip()
                    if k in ("IP", "ADDR", "HOST"):
                        info.ip = v
                    elif k in ("PORT", "RTSP_PORT"):
                        info.port = int(v) if v.isdigit() else 554
                    elif k in ("USER", "USERNAME", "USR"):
                        info.username = v
                    elif k in ("PWD", "PASSWORD", "PASS", "PW", "SC"):
                        info.password = v
                    elif k in ("SN", "SERIAL", "S/N"):
                        info.serial = v

    return info


def scan_network_cameras(subnet: str = None, timeout: float = 3.0, 
                         on_found=None) -> list[CameraInfo]:
    """
    Scan local network for cameras using ONVIF WS-Discovery.
    Falls back to port scanning common RTSP ports.
    """
    cameras = []

    if not subnet:
        subnet = _detect_subnet()
    if not subnet:
        return cameras

    # Method 1: ONVIF WS-Discovery (UDP multicast)
    try:
        onvif_results = _onvif_discover(timeout)
        for ip, info_str in onvif_results:
            cam = CameraInfo(ip=ip, brand="ONVIF")
            # Try to extract model/brand from discovery response
            if "Dahua" in info_str or "dahua" in info_str:
                cam.brand = "Dahua/Imou"
            elif "Hikvision" in info_str or "hikvision" in info_str:
                cam.brand = "Hikvision"
            cameras.append(cam)
            if on_found:
                on_found(cam)
    except Exception as e:
        log.error(f"[Discovery] ONVIF error: {e}")

    # Method 2: Port scan common RTSP ports on subnet
    if not cameras:
        base_ip = ".".join(subnet.split(".")[:3])
        found_ips = _scan_rtsp_ports(base_ip, timeout=timeout, on_found=on_found)
        for ip in found_ips:
            if not any(c.ip == ip for c in cameras):
                cam = CameraInfo(ip=ip)
                cameras.append(cam)
                if on_found:
                    on_found(cam)

    return cameras


def _detect_subnet() -> Optional[str]:
    """Detect local subnet from default gateway."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None


def _onvif_discover(timeout: float = 3.0) -> list[tuple[str, str]]:
    """Send ONVIF WS-Discovery probe and collect responses."""
    results = []

    probe = """<?xml version="1.0" encoding="utf-8"?>
    <Envelope xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
              xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
              xmlns="http://www.w3.org/2003/05/soap-envelope">
        <Header>
            <a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
            <a:MessageID>urn:uuid:f1c2d3e4-5678-abcd-ef01-234567890abc</a:MessageID>
            <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
        </Header>
        <Body>
            <d:Probe>
                <d:Types>dn:NetworkVideoTransmitter</d:Types>
            </d:Probe>
        </Body>
    </Envelope>"""

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)

        # WS-Discovery multicast address
        sock.sendto(probe.encode(), ("239.255.255.250", 3702))

        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                response = data.decode(errors="replace")
                # Avoid duplicates
                if not any(r[0] == ip for r in results):
                    results.append((ip, response))
            except socket.timeout:
                break
            except Exception:
                continue

        sock.close()
    except Exception as e:
        log.error(f"[Discovery] ONVIF probe error: {e}")

    return results


def _scan_rtsp_ports(base_ip: str, timeout: float = 1.0, on_found=None) -> list[str]:
    """Quick scan common RTSP port 554 on subnet."""
    found = []
    threads = []

    def check_port(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            result = s.connect_ex((ip, 554))
            s.close()
            if result == 0:
                found.append(ip)
        except Exception:
            pass

    for i in range(1, 255):
        ip = f"{base_ip}.{i}"
        t = threading.Thread(target=check_port, args=(ip,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=timeout + 1)

    return found
