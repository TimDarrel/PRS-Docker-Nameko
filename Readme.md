# PRS Nameko — Pembuatan Rencana Studi V1

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
    │
    ▼
[ MySQL: prs_db ]  ← Persistent storage
```
 
The gateway exposes HTTP endpoints and forwards all calls to `prs_service` via RabbitMQ RPC. The service layer handles all database operations.
 
---

## Prerequisites

If your planning to run this on your window device, make sure you have this:

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

2. Open a terminal in the project root folder (`PRS_NAMEKO/`).

3. Start all containers:
   ```bash
   docker compose up -d
   ```

4. Wait until you see:
   ```
   prs_service | Connected to amqp://guest:**@rabbitmq:5672//
   ```
   This means everything is up and running.

5. The API is now available at:
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
| PUT | `/prs/<id_prs>/verify` | Approve/reject detail lines |
| PUT | `/prs/semester/<id_semester>/verify` | Approve/reject detail lines |
| POST | `/prs/transkrip/<id_semester>` | Push validated peserta to transkrip |
| POST | `/prs/detail/<id_detail_prs>/jadwal/snapshot` | Snapshot a new jadwal into `jadwal_ss` |
| POST | `/prs/jadwal/snapshot/<id_detail_prs>` | Sync `jadwal_ss` when jadwal changes (edits in place) |
| GET | `/debug/dump` | **Dev only** — dumps all PRS, PRS_Detail, and Jadwal_SS data. Do not expose in production. |

---

## Service Dependencies

This service expects a `penawaran_kelas_service` to be reachable over RabbitMQ
(declared via `RpcProxy("penawaran_kelas_service")` in `service.py`).

> **Current status:** This proxy is not yet wired to a real call. `create_prs_detail`
> currently inserts **dummy jadwal data** into `jadwal_ss` (see the `TODO` comment
> in `service.py`). Once Penawaran Kelas exposes its jadwal-fetching RPC method,
> update `create_prs_detail` to call `self.penawaran_kelas_rpc.<method_name>(id_kelas)`
> instead of using the dummy data.
>
> If `penawaran_kelas_service` is not running on the same RabbitMQ instance, calls
> to `self.penawaran_kelas_rpc` (once wired) will hang/timeout — make sure both
> services share the same RabbitMQ broker/network in `docker-compose.yml`.

---

## Database Migration Note

The `jadwal_ss.version` column has been removed from active use. If your database
was created with an earlier schema that includes this column, drop it with:

```sql
ALTER TABLE jadwal_ss DROP COLUMN version;
```

Or do a fresh start with `docker compose down -v && docker compose up --build`
if you don't need to preserve existing data.

---

## Other Services

| Service | URL |
|---|---|
| RabbitMQ Dashboard | http://localhost:15672 (guest / guest) |
| MySQL | localhost:3306 (user: prs_user, password: prs_password) |