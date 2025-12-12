import struct
import sys

###############################################################################
# Basic MIDI helpers
###############################################################################

def read_uint32_be(data, offset):
    value = struct.unpack(">I", data[offset:offset+4])[0]
    return value, offset + 4

def read_uint16_be(data, offset):
    value = struct.unpack(">H", data[offset:offset+2])[0]
    return value, offset + 2

def read_vlq(data, offset):
    """
    Read a MIDI-style VLQ from data[offset:].
    Return (value, new_offset).
    """
    value = 0
    while True:
        b = data[offset]
        offset += 1
        value = (value << 7) | (b & 0x7F)
        if (b & 0x80) == 0:
            break
    return value, offset

def write_vlq(value):
    """
    Encode an integer as a MIDI-style VLQ.
    """
    bytes_ = [value & 0x7F]
    value >>= 7
    while value > 0:
        bytes_.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(bytes_)


###############################################################################
# SXQ parsing: extract Ga-11 lanes per MTrk
###############################################################################

def parse_sxq_ga11_tracks(sxq_bytes):
    """
    Parse SXQ bytes and return a list of tracks, each containing Ga-11 lanes:

    [
      {
        "track_index": int,
        "lanes": [
            {"pitch": int, "velocity": int, "delta_ticks": int},
            ...
        ]
      },
      ...
    ]
    """
    tracks = []
    offset = 0
    file_len = len(sxq_bytes)

    # Validate header
    if sxq_bytes[0:4] != b"MThd":
        raise ValueError("Not an SXQ/MIDI-style file: missing MThd")
    offset += 4

    header_len, offset = read_uint32_be(sxq_bytes, offset)
    offset += header_len  # skip header contents

    track_index = 0

    # Iterate over all MTrk chunks
    while offset < file_len:
        if sxq_bytes[offset:offset+4] != b"MTrk":
            # No more tracks or unexpected chunk
            break

        offset += 4
        track_len, offset = read_uint32_be(sxq_bytes, offset)
        track_end = offset + track_len

        lanes = []
        track_offset = offset

        while track_offset < track_end:
            # Event delta-time (we don't use it musically, but must consume it)
            event_delta, track_offset = read_vlq(sxq_bytes, track_offset)
            if track_offset >= track_end:
                break

            status = sxq_bytes[track_offset]
            track_offset += 1

            if status == 0xFF:
                # Meta event
                if track_offset >= track_end:
                    break
                meta_type = sxq_bytes[track_offset]
                track_offset += 1

                meta_len, track_offset2 = read_vlq(sxq_bytes, track_offset)
                track_offset = track_offset2

                if meta_type == 0x7F:
                    # Vendor-specific: check for "Ga-11"
                    vendor_data = sxq_bytes[track_offset:track_offset+meta_len]
                    track_offset += meta_len

                    if len(vendor_data) >= 5 and vendor_data[0:2] == b"Ga":
                        subtype = vendor_data[2]
                        if subtype == 0x11:
                            # Ga-11 lane: pitch/velocity + spacing
                            pitch_byte = vendor_data[4]
                            velocity = vendor_data[5]
                            midi_note = pitch_byte - 12

                            # Immediately following Ga-11, SXQ stores a delta-time VLQ
                            # that encodes the spacing between hits.
                            note_spacing_ticks, track_offset = read_vlq(
                                sxq_bytes, track_offset
                            )

                            lanes.append({
                                "pitch": midi_note,
                                "velocity": velocity,
                                "delta_ticks": note_spacing_ticks,
                            })
                        else:
                            # Other Ga subtype; ignore but already consumed
                            pass
                    else:
                        # Some other vendor event; ignore
                        pass
                else:
                    # Other meta event: skip its data payload
                    track_offset += meta_len

            elif status in (0xF0, 0xF7):
                # SysEx: read length and skip payload
                sysex_len, track_offset2 = read_vlq(sxq_bytes, track_offset)
                track_offset = track_offset2 + sysex_len

            else:
                # MIDI channel event; consume channel data bytes
                high_nibble = status & 0xF0
                if high_nibble in (0xC0, 0xD0):  # Program change / Channel pressure
                    track_offset += 1
                else:
                    track_offset += 2

        tracks.append({
            "track_index": track_index,
            "lanes": lanes,
        })

        track_index += 1
        offset = track_end

    return tracks


###############################################################################
# Build a multitrack MIDI file from SXQ Ga-11 tracks
###############################################################################

def build_multitrack_midi(sxq_tracks, ppqn=960, bars=4, tempo_bpm=120):
    """
    Build a Standard MIDI File (Format 1) as bytes, with:

    - Track 0: Master tempo / time signature
    - One additional MIDI track per SXQ track (even if some are empty)
    """
    ticks_per_bar = 4 * ppqn
    seq_len_ticks = bars * ticks_per_bar
    mpq = int(60_000_000 / tempo_bpm)  # microseconds per quarter note

    midi_tracks = []

    # -------------------------------------------------------------------------
    # Track 0: Conductor (tempo, time sig)
    # -------------------------------------------------------------------------
    t0 = bytearray()

    # Track name
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x03])  # Meta: Track Name
    t0_name = b"Master"
    t0 += write_vlq(len(t0_name))
    t0 += t0_name

    # Tempo
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x51, 0x03])  # Set Tempo
    t0 += mpq.to_bytes(3, "big")

    # Time signature: 4/4
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x58, 0x04, 0x04, 0x02, 0x18, 0x08])

    # End of track
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x2F, 0x00])

    midi_tracks.append(t0)

    # -------------------------------------------------------------------------
    # One MIDI track per SXQ track
    # -------------------------------------------------------------------------
    for tr in sxq_tracks:
        lanes = tr["lanes"]
        track_bytes = bytearray()

        # Track name
        track_bytes += write_vlq(0)
        track_bytes += bytes([0xFF, 0x03])  # Meta: Track Name
        name_str = f"SXQ Track {tr['track_index']}"
        name_bytes = name_str.encode("ascii", errors="replace")
        track_bytes += write_vlq(len(name_bytes))
        track_bytes += name_bytes

        # If no Ga-11 in this SXQ track, just end it
        if not lanes:
            track_bytes += write_vlq(0)
            track_bytes += bytes([0xFF, 0x2F, 0x00])
            midi_tracks.append(track_bytes)
            continue

        # Collect note events: (tick, is_on, pitch, velocity)
        events = []

        for lane in lanes:
            pitch = lane["pitch"]
            vel = lane["velocity"]
            delta_ticks = lane["delta_ticks"]
            if delta_ticks <= 0:
                continue

            t = 0
            # Simple rule: note length = half spacing, at least a 32nd
            note_len = max(delta_ticks // 2, ppqn // 8)

            while t < seq_len_ticks:
                # Note on
                events.append((t, True, pitch, vel))
                # Note off
                off_tick = t + note_len
                if off_tick <= seq_len_ticks:
                    events.append((off_tick, False, pitch, 0))
                t += delta_ticks

        # Sort events: by time, and note-offs before note-ons at same tick
        events.sort(key=lambda e: (e[0], 0 if not e[1] else 1))

        # Emit events with proper delta-times and running status
        last_tick = 0
        running_status = None

        for tick, is_on, pitch, vel in events:
            dt = tick - last_tick
            last_tick = tick

            track_bytes += write_vlq(dt)

            status = 0x90 if is_on else 0x80  # Note On/Off, channel 0
            if status != running_status:
                track_bytes.append(status)
                running_status = status

            track_bytes.append(pitch & 0x7F)
            track_bytes.append(vel & 0x7F)

        # End of track
        track_bytes += write_vlq(0)
        track_bytes += bytes([0xFF, 0x2F, 0x00])

        midi_tracks.append(track_bytes)

    # -------------------------------------------------------------------------
    # Build final SMF (Format 1)
    # -------------------------------------------------------------------------
    midi_bytes = bytearray()

    # MThd
    midi_bytes += b"MThd"
    midi_bytes += struct.pack(">I", 6)      # header length
    midi_bytes += struct.pack(">H", 1)      # format 1 (multitrack)
    midi_bytes += struct.pack(">H", len(midi_tracks))  # number of tracks
    midi_bytes += struct.pack(">H", ppqn)   # division (PPQN)

    # Each MTrk
    for trk_data in midi_tracks:
        midi_bytes += b"MTrk"
        midi_bytes += struct.pack(">I", len(trk_data))
        midi_bytes += trk_data

    return bytes(midi_bytes)


###############################################################################
# Top-level convenience function
###############################################################################

def sxq_to_midi_multitrack(sxq_path, midi_path, bars=4, tempo_bpm=120):
    """
    High-level conversion: SXQ file → multitrack MIDI file.
    """
    with open(sxq_path, "rb") as f:
        sxq_bytes = f.read()

    sxq_tracks = parse_sxq_ga11_tracks(sxq_bytes)
    midi_bytes = build_multitrack_midi(sxq_tracks, ppqn=960, bars=bars, tempo_bpm=tempo_bpm)

    with open(midi_path, "wb") as f:
        f.write(midi_bytes)

    print(f"Converted {sxq_path} → {midi_path}")
    for tr in sxq_tracks:
        print(f"SXQ track {tr['track_index']} has {len(tr['lanes'])} Ga-11 lane(s)")

sxq_to_midi_multitrack(sys.argv[1], sys.argv[2])