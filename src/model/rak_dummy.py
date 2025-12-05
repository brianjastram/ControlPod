import logging

log = logging.getLogger(__name__)

class DummyRAK:
    def __init__(self):
        self._downlink = None

    def send_data(self, payload):
        log.info(f"[SIM] uplink sent (simulated)")
        return "SIM_OK"

    def check_downlink(self):
        if self._downlink:
            dl = self._downlink
            self._downlink = None
            return dl
        return None

    def inject(self, hex_payload: str):
        log.info(f"[SIM] Injected downlink payload: {hex_payload}")
        self._downlink = hex_payload

# TODO: Is this needed? It doesn't appear to be used anywhere
def inject_downlink(hex_payload: str):
    """
    Bench helper: inject a hex payload as if it arrived from RAK.

    Example:
        inject_downlink("53455453544152543D302E3535")  # SETSTART=0.55
        inject_downlink("30")                          # override OFF (ASCII '0')
        inject_downlink("31")                          # override ON  (ASCII '1')
    """
    global rak
    try:
        rak.inject(hex_payload)
    except Exception:
        log.error("inject_downlink() called but DummyRAK is not active.")