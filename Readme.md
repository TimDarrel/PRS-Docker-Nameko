# PRS Nameko — Pembuatan Rencana Studi

A microservice-based academic study plan system built with Nameko, RabbitMQ, Flask, and MySQL.

---

## Architecture

```
HTTP Client
    │
    ▼
[ gateway.py ]  ← HTTP layer (Nameko web handlers)
    │  RpcProxy("prs_service")
    ▼
[ service.py ]  ← Business logic (Nameko RPC service)
    │  RpcProxy("penawaran_kelas")      ← fetches jadwal & kuota at enrollment
    │  RpcProxy("transkrip_service")    ← push validated peserta to transkrip
    ▼
[ MySQL: prs_db ]  ← Persistent storage
```

The gateway exposes HTTP endpoints and forwards all calls to `prs_service` via RabbitMQ RPC. The service layer handles all database operations and integrates with two external services:

- **penawaran_kelas** — provides kelas capacity (`get_kelas`) and jadwal (`get_jadwal`, `get_ruangan`) at enrollment time. Snapshots are stored in `jadwal_ss`.
- **transkrip_service** — receives validated peserta data via `push_peserta_to_transkrip`.

---

## Prerequisites

If you're planning to run this on your Windows device, make sure you have the following:

### 1. WSL (Windows Subsystem for Linux)

Required for running Docker on Windows.

1. Open PowerShell as Administrator and run:
   ```
   wsl --install
   ```
2. Restart your computer when prompted.
3. After restart, open WSL and set up your Linux username and password.

> If WSL is already installed, make sure it's on version 2:
> ```
> wsl --set-default-version 2
> ```

### 2. Docker Desktop

Used to build and run the containers.

1. Download Docker Desktop from [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
2. Run the installer and follow the setup steps.
3. Make sure **"Use WSL 2 instead of Hyper-V"** is checked during installation.
4. After installation, open Docker Desktop and wait until it shows **"Engine running"** in the bottom left.

---

## Running the Project

1. Clone or download this repository.

2. Create the shared Docker network (required once):
   ```bash
   docker network create prs
   ```

3. Open a terminal in the project root folder (`PRS_NAMEKO/`).

4. Start all containers:
   ```bash
   docker compose up -d
   ```

5. Wait until you see:
   ```
   prs_service | Connected to amqp://guest:**@rabbitmq:5672//
   ```
   This means everything is up and running.

6. The API is now available at:
   ```
   http://localhost:5000
   or
   http://<public_ip>:5000
   ```

---

## Stopping the Project

To stop all containers:
```bash
docker compose down
```

To stop and wipe the database (fresh start):
```bash
docker compose down -v
docker compose up --build
```

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/prs` | Create new PRS |
| GET | `/prs/<id_mahasiswa>/<id_semester>` | Get PRS header |
| POST | `/prs/<id_prs>/detail` | Add kelas to PRS |
| GET | `/prs/<id_prs>/detail` | Get detail by PRS |
| GET | `/prs/detail/<id_semester>` | Get detail by semester |
| GET | `/prs/detail/kelas/<id_kelas>` | Get detail by kelas |
| GET | `/prs/kelas/<id_kelas>/jumlah` | Count students in a kelas |
| GET | `/prs/kelas/jumlah` | Count students in all kelas |
| PUT | `/prs/<id_prs>/verify` | Auto-verify single PRS (priority + capacity + SKS cap) |
| PUT | `/prs/semester/<id_semester>/verify` | Auto-verify all PRS in a semester (shared capacity pool) |
| POST | `/prs/transkrip/<id_semester>` | Push validated peserta to transkrip |
| PUT | `/prs/jadwal/invalidate/<id_kelas>` | Mark all jadwal snapshots for a kelas as outdated |
| POST | `/prs/detail/<id_detail_prs>/jadwal/snapshot` | Snapshot a new jadwal into `jadwal_ss` |
| POST | `/prs/jadwal/snapshot/<id_detail_prs>` | Sync `jadwal_ss` when jadwal changes (upsert in place) |
| GET | `/debug/dump` | **Dev only** — dumps all PRS, PRS_Detail, Jadwal_SS, and kelas_config data. Do not expose in production. |

### Request Body Examples

**POST /prs**
```json
{
  "id_mahasiswa": 10,
  "id_semester": 2,
  "dosen_wali_id": 20
}
```

**POST /prs/\<id_prs\>/detail**
```json
{
  "id_kelas": 201,
  "id_mata_kuliah": 1,
  "sks": 3,
  "prioritas": 1
}
```
> `prioritas` is optional (default: 1). Valid values: `1` (utama), `2` (cadangan 1), `3` (cadangan 2).
> Adding a kelas automatically calls `penawaran_kelas` to fetch and snapshot kapasitas + jadwal.

**POST /prs/detail/\<id_detail_prs\>/jadwal/snapshot** and **POST /prs/jadwal/snapshot/\<id_detail_prs\>**
```json
{
  "jadwal": [
    {
      "id_jadwal": 2010,
      "hari": "Senin",
      "jam_mulai": "08:00",
      "jam_selesai": "09:40",
      "ruangan": "GKB1-201",
      "tipe": "teori"
    }
  ]
}
```

---

## Verification Logic

`verify_prs` and `verify_prs_by_semester` apply the following rules in order:

1. **Priority fallthrough** — for each mata kuliah, check kelas with `prioritas=1` first. If the class is full, fall through to `prioritas=2`, then `prioritas=3`. Only the winning row is `approved`; the rest are `rejected`.
2. **Capacity check** — uses `kelas_config.kapasitas` (default: 40). Capacity is consumed first by higher-priority approvals in `verify_prs_by_semester`.
3. **SKS cap** — total approved SKS per student cannot exceed **24 SKS**. Any kelas that would push the total over the cap is `rejected`.

After verification, PRS status is updated to `validated`.

---

## Database Schema

| Table | Description |
|---|---|
| `prs` | PRS header — one per mahasiswa per semester |
| `prs_detail` | Individual kelas entries with prioritas and status_validasi |
| `jadwal_ss` | Jadwal snapshot at enrollment time (from Penawaran Kelas) |
| `kelas_config` | Class capacity — seeded from `init.sql`, synced from Penawaran Kelas at enrollment |

**prs.status values:** `draft` → `process` → `validated`

**prs_detail.status_validasi values:** `pending` → `approved` / `rejected`

---

## Service Dependencies

This service integrates with two external Nameko services over RabbitMQ:

### penawaran_kelas

Called by `create_prs_detail` to:
- Fetch class capacity: `penawaran_kelas_rpc.get_kelas(kelas_id=...)`
- Fetch jadwal list: `penawaran_kelas_rpc.get_jadwal(kelas_id=...)`
- Fetch room info: `penawaran_kelas_rpc.get_ruangan(ruang_id=...)`

The returned kapasitas is saved into `kelas_config`. All jadwal rows (where `is_outdated=False`) are snapshotted into `jadwal_ss`.

> **If `penawaran_kelas` is not running**, calls to `create_prs_detail` will hang/timeout. Make sure both services share the same RabbitMQ broker and Docker network in `docker-compose.yml`.

### transkrip_service

Called by `push_peserta_to_transkrip` to deliver validated enrollment data for a semester.

---

## Jadwal Snapshot Lifecycle

When a kelas is added to a PRS (`create_prs_detail`), the current jadwal is snapshotted into `jadwal_ss`. The lifecycle is:

1. **Snapshot on enrollment** — `create_prs_detail` auto-calls `penawaran_kelas` and inserts rows into `jadwal_ss` (`is_outdated=0`).
2. **Invalidate on change** — when Penawaran Kelas modifies a jadwal, it calls `PUT /prs/jadwal/invalidate/<id_kelas>` to flag all related snapshots as `is_outdated=1`.
3. **Sync snapshot** — `POST /prs/jadwal/snapshot/<id_detail_prs>` updates `jadwal_ss` in place (delete removed rows, upsert changed/new rows, reset `is_outdated=0`).

---

## Database Migration Note

The `jadwal_ss.version` column has been removed from the schema. If your database was created with an earlier schema that includes this column, drop it with:

```sql
ALTER TABLE jadwal_ss DROP COLUMN version;
```

Or do a fresh start if you don't need to preserve existing data:
```bash
docker compose down -v && docker compose up --build
```

---

## Other Services

| Service | URL |
|---|---|
| RabbitMQ Dashboard | http://localhost:15672 (guest / guest) |
| MySQL | localhost:3306 (user: prs_user, password: prs_password) |
