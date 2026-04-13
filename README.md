# Control4 Media — Home Assistant Custom Integration

A full-featured HACS custom component that exposes every Control4 audio/video zone as native Home Assistant entities, with real-time state sync, source browsing, zone grouping, and volume control.

---

## Features

| Capability | HA Entity |
|---|---|
| Play/Pause/Stop transport | `media_player` |
| Audio & Video source selection | `media_player` (source list + media browser) |
| Volume control | `media_player` + `number` slider |
| Mute toggle | `media_player` + `switch` |
| Zone power on/off | `switch` |
| Zone grouping (leader/follower) | HA Services |
| Real-time state push | WebSocket from Director |
| Diagnostic dump | HA Diagnostics |

---

## Requirements

- Home Assistant 2024.1 or later
- Control4 OS 2.10+ or OS 3.x controller
- `pyControl4 >= 1.5.0` (installed automatically via `manifest.json`)
- Your **Control4 account** email + password (same as the Control4 app)
- The **local IP address** of your Control4 controller

> **Note:** This integration talks to the Director's local REST API over HTTPS. Your HA instance must be on the same local network as the Control4 controller, or reachable via VPN. It uses your cloud account credentials only to obtain a local bearer token — no cloud dependency after setup.

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → ⋮ menu → **Custom repositories**
2. Add your fork/clone URL and select category **Integration**
3. Search for "Control4 Media" and install
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/control4_media/` folder into:
   ```
   <config>/custom_components/control4_media/
   ```
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Control4 Media**
3. Enter:
   - **Email** — your Control4 account email
   - **Password** — your Control4 account password
   - **Controller IP** — local IP of your Control4 controller (e.g. `192.168.1.25`)

### Finding your Controller IP

- **Control4 App**: Settings → Controller → Network
- **Composer Pro**: System → Controller Properties → Network tab
- **Router DHCP table**: look for a device named `Control4-*`

---

## Finding Room IDs

Room IDs are needed for the zone grouping services. There are two ways to find them:

### Option 1 — HA Diagnostics (easiest)
1. Go to **Settings → Devices & Services → Control4 Media**
2. Click **Download Diagnostics**
3. Open the JSON file — the `coordinator.rooms` array lists every room with its `id` and `name`

### Option 2 — Composer Pro
1. Open Composer Pro and connect to your controller
2. Hover over any room in the project tree
3. The tooltip shows the item ID

---

## Entities Created Per Room

For a room named **Living Room** (item ID 42), the following entities are created:

| Entity ID | Type | Description |
|---|---|---|
| `media_player.living_room` | media_player | Full A/V control + source browser |
| `number.living_room_volume` | number | Volume slider 0–100 |
| `switch.living_room_power` | switch | Room power on/off |
| `switch.living_room_mute` | switch | Mute toggle |

All entities are grouped under a single **Device** called "Living Room" in HA.

---

## Media Browser

The `media_player` entities support the **HA Media Browser** (the browse button in the Lovelace media player card). Browsing presents two folders:

```
📁 Audio Sources
   🎵 My Music
   🎵 Spotify
   🎵 Pandora
📁 Video Sources
   📺 Apple TV
   📺 Cable Box
   📺 Blu-ray
```

Tapping any source selects it in that room immediately.

---

## Zone Grouping

Zone grouping lets you link rooms so they play the same content at the same volume. Changes to the leader's volume, mute, or source are mirrored to all followers in real time.

### Service: `control4_media.group_zones`

```yaml
service: control4_media.group_zones
data:
  leader_room_id: 42        # Living Room
  follower_room_ids:
    - 55                    # Kitchen
    - 67                    # Dining Room
    - 89                    # Back Patio
```

### Service: `control4_media.ungroup_zones`

```yaml
service: control4_media.ungroup_zones
data:
  room_ids:
    - 55    # Remove Kitchen from its group
```

### Service: `control4_media.sync_volume_to_group`

Force-syncs the leader's current volume to all followers (useful after a follower was adjusted manually):

```yaml
service: control4_media.sync_volume_to_group
data:
  leader_room_id: 42
```

---

## Example Automations

### Party Mode — group all zones and play music

```yaml
alias: Party Mode On
sequence:
  - service: control4_media.group_zones
    data:
      leader_room_id: 42
      follower_room_ids: [55, 67, 89, 101]
  - service: media_player.select_source
    target:
      entity_id: media_player.living_room
    data:
      source: "Spotify"
  - service: media_player.volume_set
    target:
      entity_id: media_player.living_room
    data:
      volume_level: 0.45
```

### Good Night — turn off all zones

```yaml
alias: Good Night
sequence:
  - service: control4_media.ungroup_zones
    data:
      room_ids: [42, 55, 67, 89, 101]
  - service: switch.turn_off
    target:
      entity_id:
        - switch.living_room_power
        - switch.kitchen_power
        - switch.dining_room_power
        - switch.back_patio_power
        - switch.master_bedroom_power
```

### Arrive Home — start music in entryway, then expand

```yaml
alias: Arrive Home
trigger:
  - platform: state
    entity_id: person.owner
    to: home
sequence:
  - service: media_player.select_source
    target:
      entity_id: media_player.entryway
    data:
      source: "My Music"
  - service: media_player.volume_set
    target:
      entity_id: media_player.entryway
    data:
      volume_level: 0.30
  - delay: "00:00:30"
  - service: control4_media.group_zones
    data:
      leader_room_id: 10      # Entryway
      follower_room_ids: [42, 55]
```

### Morning Routine — ramp up volume gradually

```yaml
alias: Morning Volume Ramp
sequence:
  - repeat:
      count: 10
      sequence:
        - service: media_player.volume_up
          target:
            entity_id: media_player.kitchen
        - delay: "00:00:05"
```

---

## Lovelace Card Example

```yaml
type: media-control
entity: media_player.living_room
```

Or a full room card combining all entities:

```yaml
type: entities
title: Living Room Audio
entities:
  - entity: media_player.living_room
  - entity: number.living_room_volume
    name: Volume
  - entity: switch.living_room_mute
    name: Mute
  - entity: switch.living_room_power
    name: Power
```

---

## Troubleshooting

**Entities show as unavailable after setup**
- Confirm the controller IP is reachable from HA: `ping <controller-ip>`
- Check that port 443 is not blocked between HA and the controller
- Verify your Control4 account credentials work in the Control4 app

**Sources list is empty**
- Your OS version may structure the `get_ui_configuration` response differently. Download diagnostics and check the `rooms[].audio_sources` arrays. Open an issue with the redacted diagnostic dump.

**Volume slider doesn't update in real time**
- The WebSocket may not have connected. Check HA logs for `Websocket disconnected` warnings. The 30s polling fallback will still keep state reasonably fresh.

**`ROOM_ON` command doesn't work**
- Some Control4 configurations don't support `ROOM_ON` standalone. Use `media_player.select_source` instead — selecting a source automatically powers the room on.

---

## Architecture

```
HA Core
  └── ConfigEntry (one per controller)
        └── Control4MediaCoordinator
              ├── C4Director (REST, HTTPS/443)
              ├── C4Websocket (WSS, real-time push)
              └── Platforms
                    ├── media_player.*   (per room)
                    ├── number.*         (per room)
                    ├── switch.*         (2 per room: power + mute)
                    └── diagnostics
        └── Services (domain-level, shared)
              ├── control4_media.group_zones
              ├── control4_media.ungroup_zones
              └── control4_media.sync_volume_to_group
```

---

## Credits

Built on top of [pyControl4](https://github.com/lawtancool/pyControl4) by lawtancool, which powers the official HA Control4 integration.
