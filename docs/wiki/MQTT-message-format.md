# MQTT message format

There is no single standard for spots over MQTT, so spiderd accepts the most
common shapes.

## Message shapes

Each message can be:

- a JSON object: `{"qrg": "14025.0", "dx": "K1ABC", …}`
- a JSON array of objects
- an object wrapped in `data`, `spot` or `spots`: `{"data": {…}}`
- a plain DX cluster line: `DX de EA1ABC: 14025.0 K1ABC CW 599 1234Z`

Messages that cannot be read as spots are ignored, for example solar data
published on the same broker.

## Recognized fields

For each item, the first field present is used.

| Data | Fields |
| --- | --- |
| Frequency | `frequencyHz`, `qrg`, `frequency`, `freq` |
| DX callsign | `dx`, `call`, `callsign`, `dxcall` |
| Spotter | `spotter`, `src`, `de` |
| Mode | `mode`, `submode`, `md` |
| Comment | `comment`, `cmt`, `info` |
| Time | `timestamp`, `isots`, `utc`, `time`, `ts` |
| Band | `band` |

A spot needs at least a frequency and a DX callsign.

### Frequency

Values may be in Hz, kHz or MHz; spiderd decides by size:

| Value | Read as |
| --- | --- |
| below 1000 | MHz |
| below 1 000 000 | kHz |
| otherwise | Hz |

A decimal comma is accepted. If a `band` is given (`"20m"`, `20` or `"20"`) and
the frequency falls outside it by a factor of 10, 100 or 1000, it is rescaled
into the band. Some feeds have this scaling mistake.

### Mode and color

The mode is taken from, in this order:

1. the mode fields;
2. a mode word in the comment (e.g. `FT8 -12 dB`);
3. the topic name: topics containing `cw` count as CW, topics containing
   `dig` or `ft8` as digital.

A generic mode such as `DIG` or `DIGI` is replaced by a specific mode found in
the comment.

If no mode is known at all, the color comes from the band plan:

| Frequency | Color group |
| --- | --- |
| FT8/FT4 frequencies | digital |
| CW segment | CW |
| Digital segment | digital |
| Anywhere else | phone |

### Time

The time can be:

- Unix seconds or milliseconds;
- ISO 8601 text, e.g. `2026-10-01T13:53:29Z`. Text without a time zone is
  taken as UTC.

Without a time, the reception time is used.

## Example

```json
{
  "isots": "2026-10-01T13:53:29",
  "src": "EA4ABC-#",
  "dx": "JA1XYZ",
  "qrg": "14074.0",
  "band": 20,
  "mode": "DIG",
  "cmt": "FT8 -12dB"
}
```

This becomes JA1XYZ on 14.074 MHz, mode FT8, drawn in the digital color.
