from operator import truediv
import re
import json
from enum import Enum
from logging import Logger
from typing import Iterable, Set, Dict

from tg3442de_exporter.html_metrics_extractor import HtmlMetricsExtractor

from prometheus_client import Metric
from prometheus_client.metrics_core import (
    GaugeMetricFamily,
)

DOCSIS_STATUS   = 'docsis_status'
GET_STATUS_DOCSIS = '/php/status_docsis_data.php'

class ChannelType(Enum):
    SCQAM = 'SC-QAM'
    OFDMA = 'OFDMA'
    OFDM  = 'OFDM'

    # default case for all future unknown channel type
    UNKNOWN = "unknown"


class ChannelModulation(Enum):
    QAM4096 = '4096QAM'
    QAM2048 = '2048QAM'
    QAM1024 = '1024QAM'
    QAM256  = '256QAM'
    QAM128  = '128QAM'
    QAM64   = '64QAM'
    QAM16   = '16QAM'
    QPSK    = 'QPSK'

    # reported by unlocked channels
    UNSUPPORTED = 'UNSUPPORTED'

    # default case for all future unknown channel modulation
    UNKNOWN = 'unknown'

class LockStatus(Enum):
    LOCKED   = True
    UNLOCKED = False

class DocsisStatusExtractor(HtmlMetricsExtractor):
    def __init__(self, logger: Logger, exporter_config: Dict):
        super(DocsisStatusExtractor, self).__init__(
            DOCSIS_STATUS, {GET_STATUS_DOCSIS}, logger
        )
        self.logger = logger

    def get_channel_modulation(self,modulation):
        try:
            enum_channel_modulation = ChannelModulation(modulation)
        except ValueError:
            self._logger.warning(f"Unknown channel modulation '{modulation}'.")
            enum_channel_modulation = ChannelModulation.UNKNOWN
        return enum_channel_modulation.value

    def get_channel_type(self,channel_type):
        try:
            enum_channel_type = ChannelType(channel_type)
        except ValueError:
            self._logger.warning(f"Unknown channel modulation '{channel_type}'.")
            enum_channel_type = ChannelType.UNKNOWN

        return enum_channel_type.value


    def extract(self, raw_htmls: Dict[str, bytes]) -> Iterable[Metric]:
        self.logger.debug("DeviceStatusExtractor")

        # parse GlobalSettings
        raw_html = raw_htmls[GET_STATUS_DOCSIS]
        if len(raw_html) < 10:
            return

        # extract json from javascript
        json_downstream_data = re.search(r".*json_dsData = (.+);.*", raw_html)[1]
        json_upstream_data = re.search(r".*json_usData = (.+);.*", raw_html)[1]
        # parse json
        downstream_data = json.loads(json_downstream_data)
        upstream_data = json.loads(json_upstream_data)
        # convert lock status to numeric values
        for d in [ upstream_data, downstream_data ]:
            for c in d:
                if c['LockStatus'] in ("ACTIVE", "Locked", "SUCCESS", "OPERATE"):
                    c['LockStatus'] = 1
                elif c['LockStatus'] == "NotLocked":
                    c['LockStatus'] = 0
                else:
                    self.logger.error(f"Unknown lock status: {c}")
                    raise ValueError("Unknown lock status")
        
        CHANNEL_ID = 'channel_id'
        CHANNEL_TYPE = 'channel_type'
        CHANNEL_MODULATION = 'channel_modulation'
        ds_frequency = GaugeMetricFamily(
            "tg3442de_downstream_frequency",
            "Downstream channel frequency",
            unit="MHz",
            labels=[CHANNEL_ID,CHANNEL_TYPE,CHANNEL_MODULATION],
        )
        ds_power_level = GaugeMetricFamily(
            "tg3442de_downstream_power_level",
            "Downstream channel power level",
            unit="dbmV",
            labels=[CHANNEL_ID,CHANNEL_TYPE,CHANNEL_MODULATION],
        )
        ds_snr = GaugeMetricFamily(
            "tg3442de_downstream_snr",
            "Downstream channel signal-to-noise ratio (SNR)",
            unit="db",
            labels=[CHANNEL_ID,CHANNEL_TYPE,CHANNEL_MODULATION],
        )
        ds_locked = GaugeMetricFamily(
            "tg3442de_downstream_locked",
            "Downstream locking status",
            labels=[CHANNEL_ID],
        )
        scqam_count = 0
        reported_scqam_ids = set()
        for channel in downstream_data:
            if channel["ChannelType"] == "SC-QAM":
                scqam_count += 1

            # dropped channels are fully masked: id zero, empty measurements, not locked
            if channel["PowerLevel"] == "":
                if (channel["ChannelType"] != "SC-QAM" or channel["ChannelID"] != "0"
                        or channel["Frequency"] != "" or channel["SNRLevel"] != ""
                        or channel["LockStatus"] != 0):
                    self.logger.error(f"Downstream channel row has unknown shape: {channel}")
                    raise ValueError("Downstream channel row has unknown shape")
                continue

            if channel["ChannelType"] == "SC-QAM":
                scqam_id = int(channel["ChannelID"])
                if scqam_id in reported_scqam_ids:
                    self.logger.error(f"Duplicate downstream channel id: {channel}")
                    raise ValueError("Duplicate downstream channel id")
                reported_scqam_ids.add(scqam_id)

            channel_id = channel["ChannelID"]
            channel_type = self.get_channel_type(channel['ChannelType'])
            channel_modulation = self.get_channel_modulation(channel['Modulation'])
            lock_status = channel['LockStatus']
            frequency = channel["Frequency"]
            if type(frequency) is str:
                frequency = frequency.split('~')[0]
            power_level_mV,power_level_uV = channel["PowerLevel"].split('/')
            snr_level = channel["SNRLevel"]

            labels = [channel_id.zfill(2)]
            labels_full = labels + [channel_type, channel_modulation]
            ds_locked.add_metric(labels,lock_status)
            ds_frequency.add_metric(labels_full, float(frequency))
            ds_power_level.add_metric(labels_full, float(power_level_mV))
            ds_snr.add_metric(labels_full, float(snr_level))

        # SC-QAM channel ids occupy 1..N for N table rows, so the masked rows are the unreported remainder
        if any(scqam_id < 1 or scqam_id > scqam_count for scqam_id in reported_scqam_ids):
            self.logger.error(f"Downstream channel ids exceed table size {scqam_count}: {sorted(reported_scqam_ids)}")
            raise ValueError("Downstream channel id outside table range")
        for masked_id in sorted(set(range(1, scqam_count + 1)) - reported_scqam_ids):
            ds_locked.add_metric([str(masked_id).zfill(2)], 0)
        yield from [ds_frequency, ds_power_level, ds_snr, ds_locked]

        us_frequency = GaugeMetricFamily(
            "tg3442de_upstream_frequency",
            "Upstream channel frequency",
            unit="MHz",
            labels=[CHANNEL_ID,CHANNEL_TYPE,CHANNEL_MODULATION],
        )
        us_power_level = GaugeMetricFamily(
            "tg3442de_upstream_power_level",
            "Upstream channel power level",
            unit="dbmV",
            labels=[CHANNEL_ID,CHANNEL_TYPE,CHANNEL_MODULATION],
        )
        us_locked = GaugeMetricFamily(
            "tg3442de_upstream_locked",
            "Upstream locking status",
            labels=[CHANNEL_ID],
        )

        for channel in upstream_data:
            channel_id = channel["ChannelID"]
            channel_type = self.get_channel_type(channel['ChannelType'])
            channel_modulation = self.get_channel_modulation(channel['Modulation'])
            lock_status = channel['LockStatus']
            frequency = channel["Frequency"]
            if type(frequency) is str:
                frequency = frequency.split('~')[0]
            power_level_mV,power_level_uV = channel["PowerLevel"].split('/')

            labels = [channel_id.zfill(2)]
            labels_full = labels + [channel_type, channel_modulation]
            us_locked.add_metric(labels,lock_status)
            us_frequency.add_metric(labels_full, float(frequency))
            us_power_level.add_metric(labels_full, float(power_level_mV))
        yield from [us_frequency, us_power_level,us_locked]

