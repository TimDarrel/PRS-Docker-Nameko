"""
service.py — Nameko RPC microservice for PRS (Pembuatan Rencana Studi).

Tables owned:
    prs           — header per mahasiswa per semester
    prs_detail    — kelas yang diambil, with prioritas & status_validasi
    jadwal_ss     — snapshot jadwal from Penawaran Kelas at enrollment time
    kelas_config  — kapasitas per kelas (default 40; future: synced from Penawaran Kelas)

Exposed RPC methods:
    1.  create_prs                  — insert PRS header (status=draft)
    2.  create_prs_detail           — insert one kelas into a PRS
    3.  get_prs_by_id               — fetch PRS header by id_prs
    4.  get_prs                     — fetch PRS header by id_mahasiswa + id_semester
    5.  get_prs_detail_by_semester  — all details for a given semester
    6.  get_prs_detail_by_prs_id    — all details for a given id_prs
    7.  get_prs_detail_by_kelas_id  — all details for a given id_kelas (across all PRS)
    8.  get_jumlah_mahasiswa_per_kelas — count students enrolled per kelas
    9.  verify_prs                  — auto-verify a single student PRS (priority + cap + SKS)
    10. verify_prs_by_semester      — auto-verify all PRS in a semester (shared capacity pool)
    11. push_peserta_to_transkrip   — return validated enrollments for Transkrip service
    12. invalidate_jadwal_snapshot  — mark a jadwal snapshot as outdated
    13. snapshot_jadwal             — snapshot jadwal into jadwal_ss
    14. sync_jadwal_snapshot        — update jadwal_ss when Penawaran Kelas changes a jadwal
    15. debug_dump                  — dump all rows (dev only)
"""

import os
import logging

import pymysql
from nameko.rpc import rpc, RpcProxy
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SKS = 24          # default max SKS per student per semester
DEFAULT_KAPASITAS = 40  # default class capacity (stored in kelas_config, see schema)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PRSService:
    """PRS microservice. All RPC methods return plain dicts / lists."""

    name = "prs_service"
    penawaran_kelas_rpc = RpcProxy("penawaran_kelas")
    transkrip_rpc = RpcProxy("transkrip_service")

    # -----------------------------------------------------------------------
    # DB helper
    # -----------------------------------------------------------------------

    def _db(self):
        return pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 3306)),
            user=os.getenv("DB_USER", "prs_user"),
            password=os.getenv("DB_PASSWORD", "prs_password"),
            database=os.getenv("DB_NAME", "prs_db"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    # -----------------------------------------------------------------------
    # 1. Create PRS
    # -----------------------------------------------------------------------

    @rpc
    def create_prs(self, id_mahasiswa, id_semester, dosen_wali_id):
        """
        Create a new PRS header with status='draft'.
        One PRS per mahasiswa per semester (enforced by UNIQUE KEY).
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO prs (id_mahasiswa, id_semester, dosen_wali_id, status, total_sks)
                       VALUES (%s, %s, %s, 'draft', 0)""",
                    (id_mahasiswa, id_semester, dosen_wali_id),
                )
                id_prs = cur.lastrowid
            db.commit()
            return {"message": "PRS berhasil dibuat", "id_prs": id_prs}
        except pymysql.IntegrityError:
            db.rollback()
            return {"error": "PRS untuk semester ini sudah ada"}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 2. Create PRS Detail
    # -----------------------------------------------------------------------

    @rpc
    def create_prs_detail(self, id_prs, id_kelas, id_mata_kuliah, sks, prioritas=1):
        """
        Add a kelas to an existing PRS.
        Only allowed when PRS status is 'draft'.
        prioritas: 1 (utama), 2 (cadangan 1), 3 (cadangan 2).
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status FROM prs WHERE id_prs = %s FOR UPDATE",
                    (id_prs,),
                )
                prs = cur.fetchone()
                if not prs:
                    return {"error": "PRS tidak ditemukan"}
                if prs["status"] != "draft":
                    return {"error": f"PRS status '{prs['status']}', hanya bisa tambah kelas saat draft"}

                if prioritas not in (1, 2, 3):
                    return {"error": "Prioritas harus 1, 2, atau 3"}

                cur.execute(
                    """INSERT INTO prs_detail
                           (id_prs, id_kelas, id_mata_kuliah, prioritas, sks, status_validasi)
                       VALUES (%s, %s, %s, %s, %s, 'pending')""",
                    (id_prs, id_kelas, id_mata_kuliah, prioritas, sks),
                )
                id_detail = cur.lastrowid

                
                # --- GET kuota from Kelas ---
                kelas_info = self.penawaran_kelas_rpc.get_kelas(kelas_id=id_kelas)
                kuota = kelas_info.get("kuota", DEFAULT_KAPASITAS)

                # --- GET jadwal list ---
                jadwal_raw = self.penawaran_kelas_rpc.get_jadwal(kelas_id=id_kelas)

                jadwal_list = []
                for j in jadwal_raw:
                    if j["is_outdated"]:
                        continue

                    # ruang_id is nullable in their schema
                    if j["ruang_id"]:
                        ruang_info = self.penawaran_kelas_rpc.get_ruangan(ruang_id=j["ruang_id"])
                        # nama_ruang is also nullable, fall back to kode_ruang
                        ruangan = ruang_info.get("nama_ruang") or ruang_info.get("kode_ruang", str(j["ruang_id"]))
                    else:
                        ruangan = "TBD"  # room not yet assigned

                    jadwal_list.append({
                        "id_jadwal": j["jadwal_id"],
                        "hari": j["hari"],
                        "jam_mulai": j["jam_mulai"],
                        "jam_selesai": j["jam_selesai"],
                        "ruangan": ruangan,
                        "tipe": j["tipe"],   
                    })

                # --- Save kuota into kelas_config (once, after loop) ---
                cur.execute(
                    """INSERT INTO kelas_config (id_kelas, kapasitas)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE kapasitas = VALUES(kapasitas)""",
                    (id_kelas, kuota),
                )

                # --- Snapshot all jadwal rows (once, after loop) ---
                self._snapshot_jadwal(db, id_detail, jadwal_list)

            db.commit()
            return {"message": "Kelas berhasil ditambahkan ke PRS", "id_detail_prs": id_detail}
        except pymysql.IntegrityError:
            db.rollback()
            return {"error": "Kelas ini sudah ada dalam PRS"}
        except pymysql.Error as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()
            
    # -----------------------------------------------------------------------
    # 3. Fetch PRS by id
    # -----------------------------------------------------------------------
            
    @rpc
    def get_prs_by_id(self, id_prs):
        """Called by Transkrip service to get PRS header data."""
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT * FROM prs WHERE id_prs = %s", (id_prs,))
                row = cur.fetchone()
                if not row:
                    return {"error": f"PRS {id_prs} tidak ditemukan"}
                result = self._serialize_row(row)
                # Transkrip expects: id_mahasiswa, semester, tahun_ajaran
                # Map id_semester to semester string if needed
                return result
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 4. Fetch PRS by mahasiswa + semester
    # -----------------------------------------------------------------------

    @rpc
    def get_prs(self, id_mahasiswa, id_semester):
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT * FROM prs WHERE id_mahasiswa = %s AND id_semester = %s",
                    (id_mahasiswa, id_semester),
                )
                row = cur.fetchone()
                if not row:
                    return {"error": "PRS tidak ditemukan"}
                return self._serialize_row(row)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 5. Fetch PRS Detail by semester
    # -----------------------------------------------------------------------

    @rpc
    def get_prs_detail_by_semester(self, id_semester):
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT pd.*, p.id_mahasiswa, p.dosen_wali_id, p.status AS status_prs
                       FROM prs_detail pd
                       JOIN prs p ON pd.id_prs = p.id_prs
                       WHERE p.id_semester = %s
                       ORDER BY p.id_mahasiswa, pd.prioritas""",
                    (id_semester,),
                )
                return [self._serialize_row(r) for r in cur.fetchall()]
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 6. Fetch PRS Detail by prs_id
    # -----------------------------------------------------------------------

    @rpc
    def get_prs_detail_by_prs_id(self, id_prs):
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT * FROM prs_detail
                       WHERE id_prs = %s
                       ORDER BY prioritas, id_detail_prs""",
                    (id_prs,),
                )
                rows = cur.fetchall()
                if not rows:
                    return {"error": "Tidak ada detail untuk PRS ini"}
                return [self._serialize_row(r) for r in rows]
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 7. Fetch PRS Detail by kelas
    # -----------------------------------------------------------------------

    @rpc
    def get_prs_detail_by_kelas_id(self, id_kelas):
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT pd.*, p.id_mahasiswa, p.id_semester, p.status AS status_prs
                       FROM prs_detail pd
                       JOIN prs p ON pd.id_prs = p.id_prs
                       WHERE pd.id_kelas = %s
                       ORDER BY p.id_mahasiswa""",
                    (id_kelas,),
                )
                return [self._serialize_row(r) for r in cur.fetchall()]
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 8. Jumlah mahasiswa per kelas
    # -----------------------------------------------------------------------

    @rpc
    def get_jumlah_mahasiswa_per_kelas(self, id_kelas=None):
        db = self._db()
        try:
            with db.cursor() as cur:
                if id_kelas:
                    cur.execute(
                        """SELECT id_kelas, COUNT(*) AS jumlah_mahasiswa
                           FROM prs_detail
                           WHERE id_kelas = %s AND status_validasi = 'approved'
                           GROUP BY id_kelas""",
                        (id_kelas,),
                    )
                    row = cur.fetchone()
                    return row if row else {"id_kelas": id_kelas, "jumlah_mahasiswa": 0}
                else:
                    cur.execute(
                        """SELECT id_kelas, COUNT(*) AS jumlah_mahasiswa
                           FROM prs_detail
                           WHERE status_validasi = 'approved'
                           GROUP BY id_kelas
                           ORDER BY id_kelas"""
                    )
                    return cur.fetchall()
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 9. Verify PRS — single student, auto-logic
    # -----------------------------------------------------------------------

    @rpc
    def verify_prs(self, id_prs):
        """
        Auto-verify a single student's PRS using priority + capacity + SKS rules.

        Algorithm (per mata kuliah group):
          - Sort detail lines for each id_mata_kuliah by prioritas ASC.
          - Try prioritas 1 first: approve if the kelas has remaining capacity
            AND student's running total_sks + sks <= MAX_SKS.
          - If that fails, try prioritas 2, then 3.
          - The first passing line is approved; all others for that mata kuliah
            are rejected.
          - If none pass, all lines for that mata kuliah are rejected.

        Capacity is read from kelas_config (falls back to DEFAULT_KAPASITAS).
        Already-approved enrollments from OTHER PRS count against capacity.

        PRS status after verification:
          - 'validated'  → at least one line approved
          - 'process'    → all lines rejected (dosen wali may intervene manually)
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                # Lock and fetch the PRS
                cur.execute(
                    "SELECT * FROM prs WHERE id_prs = %s FOR UPDATE",
                    (id_prs,),
                )
                prs = cur.fetchone()
                if not prs:
                    return {"error": "PRS tidak ditemukan"}
                if prs["status"] == "validated":
                    return {"error": "PRS sudah divalidasi sebelumnya"}

                # Fetch all detail lines ordered by mata kuliah, then prioritas
                cur.execute(
                    """SELECT * FROM prs_detail
                       WHERE id_prs = %s
                       ORDER BY id_mata_kuliah, prioritas, id_detail_prs""",
                    (id_prs,),
                )
                details = cur.fetchall()
                if not details:
                    return {"error": "PRS tidak memiliki detail kelas"}

                # Group lines by id_mata_kuliah
                groups = {}
                for d in details:
                    groups.setdefault(d["id_mata_kuliah"], []).append(d)

                approved_ids = []
                rejected_ids = []
                total_sks = 0

                for mk_id, lines in groups.items():
                    approved = False
                    for line in lines:
                        # Skip if adding this SKS would exceed the cap
                        if total_sks + line["sks"] > MAX_SKS:
                            continue

                        # Check current approved count for this kelas
                        cap = self._get_kapasitas(cur, line["id_kelas"])
                        cur.execute(
                            """SELECT COUNT(*) AS cnt FROM prs_detail
                               WHERE id_kelas = %s AND status_validasi = 'approved'""",
                            (line["id_kelas"],),
                        )
                        enrolled = cur.fetchone()["cnt"]
                        if enrolled >= cap:
                            continue  # Full — try next prioritas

                        # This line passes — approve it
                        approved_ids.append(line["id_detail_prs"])
                        total_sks += line["sks"]
                        approved = True
                        break  # Don't try lower-priority lines

                    if not approved:
                        rejected_ids.extend(l["id_detail_prs"] for l in lines)
                    else:
                        # Reject remaining lines for this mata kuliah
                        for line in lines:
                            if line["id_detail_prs"] not in approved_ids:
                                rejected_ids.append(line["id_detail_prs"])

                # Apply updates
                if approved_ids:
                    cur.execute(
                        f"""UPDATE prs_detail SET status_validasi = 'approved'
                            WHERE id_detail_prs IN ({','.join(['%s']*len(approved_ids))})""",
                        approved_ids,
                    )
                if rejected_ids:
                    cur.execute(
                        f"""UPDATE prs_detail SET status_validasi = 'rejected'
                            WHERE id_detail_prs IN ({','.join(['%s']*len(rejected_ids))})""",
                        rejected_ids,
                    )

                new_status = "validated" if approved_ids else "process"
                cur.execute(
                    "UPDATE prs SET status = %s, total_sks = %s WHERE id_prs = %s",
                    (new_status, total_sks, id_prs),
                )

            db.commit()
            return {
                "message": "Verifikasi PRS berhasil",
                "id_prs": id_prs,
                "status": new_status,
                "total_sks": total_sks,
                "approved": approved_ids,
                "rejected": rejected_ids,
            }
        except pymysql.Error as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 10. Verify PRS by semester — all students, shared capacity pool
    # -----------------------------------------------------------------------

    @rpc
    def verify_prs_by_semester(self, id_semester):
        """
        Auto-verify ALL pending PRS in a semester using the same
        priority + capacity + SKS rules as verify_prs, but with a
        SHARED capacity pool across all students.

        Processing order: id_mahasiswa ASC (fair FIFO — first registered
        gets priority when multiple students want the same full kelas).

        Only processes PRS with status 'draft' or 'process'.
        Already-validated PRS are skipped.

        Returns a per-PRS summary of what was approved/rejected.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                # Fetch all eligible PRS for this semester, ordered fairly
                cur.execute(
                    """SELECT * FROM prs
                       WHERE id_semester = %s
                         AND status IN ('draft', 'process')
                       ORDER BY id_mahasiswa ASC
                       FOR UPDATE""",
                    (id_semester,),
                )
                all_prs = cur.fetchall()

                if not all_prs:
                    return {"error": "Tidak ada PRS yang perlu diverifikasi untuk semester ini"}

                # ----------------------------------------------------------------
                # Capacity tracker: shared across all students in this run.
                # Seed with already-approved enrollments from validated PRS
                # so we don't double-count seats.
                # ----------------------------------------------------------------
                cur.execute(
                    """SELECT pd.id_kelas, COUNT(*) AS cnt
                       FROM prs_detail pd
                       JOIN prs p ON pd.id_prs = p.id_prs
                       WHERE p.id_semester = %s
                         AND p.status = 'validated'
                         AND pd.status_validasi = 'approved'
                       GROUP BY pd.id_kelas""",
                    (id_semester,),
                )
                # enrolled_counts[id_kelas] = how many seats already taken
                enrolled_counts = {r["id_kelas"]: r["cnt"] for r in cur.fetchall()}

                results = []

                for prs in all_prs:
                    id_prs = prs["id_prs"]

                    cur.execute(
                        """SELECT * FROM prs_detail
                           WHERE id_prs = %s
                           ORDER BY id_mata_kuliah, prioritas, id_detail_prs""",
                        (id_prs,),
                    )
                    details = cur.fetchall()

                    if not details:
                        results.append({
                            "id_prs": id_prs,
                            "id_mahasiswa": prs["id_mahasiswa"],
                            "status": "skipped",
                            "reason": "Tidak ada detail kelas",
                        })
                        continue

                    # Group by mata kuliah
                    groups = {}
                    for d in details:
                        groups.setdefault(d["id_mata_kuliah"], []).append(d)

                    approved_ids = []
                    rejected_ids = []
                    total_sks = 0

                    for mk_id, lines in groups.items():
                        approved = False
                        for line in lines:
                            if total_sks + line["sks"] > MAX_SKS:
                                continue

                            id_kelas = line["id_kelas"]
                            cap = self._get_kapasitas(cur, id_kelas)
                            current_enrolled = enrolled_counts.get(id_kelas, 0)
                            if current_enrolled >= cap:
                                continue

                            # Approve
                            approved_ids.append(line["id_detail_prs"])
                            total_sks += line["sks"]
                            enrolled_counts[id_kelas] = current_enrolled + 1  # update shared pool
                            approved = True
                            break

                        if not approved:
                            rejected_ids.extend(l["id_detail_prs"] for l in lines)
                        else:
                            for line in lines:
                                if line["id_detail_prs"] not in approved_ids:
                                    rejected_ids.append(line["id_detail_prs"])

                    # Apply DB updates for this PRS
                    if approved_ids:
                        cur.execute(
                            f"""UPDATE prs_detail SET status_validasi = 'approved'
                                WHERE id_detail_prs IN ({','.join(['%s']*len(approved_ids))})""",
                            approved_ids,
                        )
                    if rejected_ids:
                        cur.execute(
                            f"""UPDATE prs_detail SET status_validasi = 'rejected'
                                WHERE id_detail_prs IN ({','.join(['%s']*len(rejected_ids))})""",
                            rejected_ids,
                        )

                    new_status = "validated" if approved_ids else "process"
                    cur.execute(
                        "UPDATE prs SET status = %s, total_sks = %s WHERE id_prs = %s",
                        (new_status, total_sks, id_prs),
                    )

                    results.append({
                        "id_prs": id_prs,
                        "id_mahasiswa": prs["id_mahasiswa"],
                        "status": new_status,
                        "total_sks": total_sks,
                        "approved": approved_ids,
                        "rejected": rejected_ids,
                    })

            db.commit()
            return {
                "message": f"Verifikasi semester {id_semester} selesai",
                "id_semester": id_semester,
                "total_prs_diproses": len(results),
                "hasil": results,
            }
        except pymysql.Error as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 11. Push peserta to transkrip
    # -----------------------------------------------------------------------

    @rpc
    def push_peserta_to_transkrip(self, id_semester):
        db = self._db()
        try:
            with db.cursor() as cur:
                # Get all validated PRS ids for this semester
                cur.execute(
                    """SELECT id_prs, id_mahasiswa FROM prs
                    WHERE id_semester = %s AND status = 'validated'
                    ORDER BY id_mahasiswa""",
                    (id_semester,),
                )
                validated_prs = cur.fetchall()

            if not validated_prs:
                return {"error": "Tidak ada PRS validated untuk semester ini"}

            results = []
            for prs in validated_prs:
                try:
                    result = self.transkrip_rpc.push_prs_ke_krs(id_prs=prs["id_prs"])
                    results.append({
                        "id_prs": prs["id_prs"],
                        "id_mahasiswa": prs["id_mahasiswa"],
                        "status": result.get("status"),
                        "id_krs": result.get("id_krs"),
                        "message": result.get("message"),
                    })
                except Exception as e:
                    results.append({
                        "id_prs": prs["id_prs"],
                        "id_mahasiswa": prs["id_mahasiswa"],
                        "status": "error",
                        "message": str(e),
                    })

            sukses = [r for r in results if r["status"] == "ok"]
            gagal = [r for r in results if r["status"] != "ok"]

            return {
                "message": f"{len(sukses)} KRS berhasil dibuat, {len(gagal)} gagal",
                "id_semester": id_semester,
                "sukses": sukses,
                "gagal": gagal,
            }
        finally:
            db.close()
            
    # -----------------------------------------------------------------------
    # 12. Invalidate jadwal snapshot
    # -----------------------------------------------------------------------

    @rpc
    def invalidate_jadwal_snapshot(self, id_kelas):
        """
        Called when Penawaran Kelas alters a schedule.
        Flags all related snapshots across all students' PRS details as outdated,
        notifying administrators or systems that a sync is pending.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                # Find all prs_detail IDs matching this class
                cur.execute(
                    "SELECT id_detail_prs FROM prs_detail WHERE id_kelas = %s",
                    (id_kelas,)
                )
                details = cur.fetchall()
                
                if not details:
                    return {"message": "Tidak ada snapshot yang aktif untuk kelas ini", "id_kelas": id_kelas}
                
                detail_ids = [d["id_detail_prs"] for d in details]
                placeholders = ",".join(["%s"] * len(detail_ids))
                
                # Update the is_outdated flag to 1
                cur.execute(
                    f"""UPDATE jadwal_ss 
                       SET is_outdated = 1 
                       WHERE id_detail_prs IN ({placeholders})""",
                    detail_ids
                )
                
            db.commit()
            logger.info(f"Class {id_kelas} schedule invalidated. Marked snapshots as outdated.")
            return {"message": "Snapshot berhasil ditandai outdated", "id_kelas": id_kelas, "affected_records": len(detail_ids)}
        except Exception as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 13. Snapshot jadwal (internal helper + public RPC wrapper)
    # -----------------------------------------------------------------------

    def _snapshot_jadwal(self, db, id_detail_prs, jadwal_list):
        """Internal — inserts jadwal rows into jadwal_ss within an open transaction."""
        with db.cursor() as cur:
            for j in jadwal_list:
                cur.execute(
                    """INSERT INTO jadwal_ss
                           (id_jadwal, id_detail_prs, jam_mulai, jam_selesai,
                            hari, ruangan, tipe, is_outdated)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 0)""",
                    (
                        j["id_jadwal"],
                        id_detail_prs,
                        j["jam_mulai"],
                        j["jam_selesai"],
                        j["hari"],
                        j["ruangan"],
                        j["tipe"],
                    ),
                )

    @rpc
    def snapshot_jadwal(self, id_detail_prs, jadwal_list):
        """Public RPC — called by Penawaran Kelas when a new jadwal is created."""
        db = self._db()
        try:
            self._snapshot_jadwal(db, id_detail_prs, jadwal_list)
            db.commit()
            return {"message": "Snapshot jadwal berhasil dibuat", "id_detail_prs": id_detail_prs}
        except Exception as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 14. Sync jadwal snapshot
    # -----------------------------------------------------------------------

    @rpc
    def sync_jadwal_snapshot(self, id_detail_prs, jadwal_list):
        """
        Updates jadwal_ss when Penawaran Kelas notifies of a jadwal change.
        Deletes rows removed from the new list; upserts the rest.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                incoming_ids = [j["id_jadwal"] for j in jadwal_list]

                if incoming_ids:
                    placeholders = ",".join(["%s"] * len(incoming_ids))
                    cur.execute(
                        f"DELETE FROM jadwal_ss WHERE id_detail_prs = %s AND id_jadwal NOT IN ({placeholders})",
                        [id_detail_prs, *incoming_ids],
                    )
                else:
                    cur.execute(
                        "DELETE FROM jadwal_ss WHERE id_detail_prs = %s",
                        (id_detail_prs,),
                    )

                for j in jadwal_list:
                    cur.execute(
                        """UPDATE jadwal_ss
                               SET jam_mulai = %s, jam_selesai = %s,
                                   hari = %s, ruangan = %s, tipe = %s, is_outdated = 0
                           WHERE id_jadwal = %s AND id_detail_prs = %s""",
                        (j["jam_mulai"], j["jam_selesai"], j["hari"],
                         j["ruangan"], j["tipe"], j["id_jadwal"], id_detail_prs),
                    )
                    if cur.rowcount == 0:
                        cur.execute(
                            """INSERT INTO jadwal_ss
                                   (id_jadwal, id_detail_prs, jam_mulai, jam_selesai,
                                    hari, ruangan, tipe, is_outdated)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, 0)""",
                            (j["id_jadwal"], id_detail_prs, j["jam_mulai"],
                             j["jam_selesai"], j["hari"], j["ruangan"], j["tipe"]),
                        )

            db.commit()
            return {"message": "Jadwal snapshot updated", "id_detail_prs": id_detail_prs}
        except Exception as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 15. Debug dump
    # -----------------------------------------------------------------------

    @rpc
    def debug_dump(self):
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT * FROM prs ORDER BY id_prs")
                all_prs = cur.fetchall()

                cur.execute("SELECT * FROM prs_detail ORDER BY id_prs, id_detail_prs")
                all_detail = cur.fetchall()

                cur.execute("SELECT * FROM jadwal_ss ORDER BY id_detail_prs, id_jadwal_ss")
                all_jadwal = cur.fetchall()

                cur.execute("SELECT * FROM kelas_config ORDER BY id_kelas")
                all_config = cur.fetchall()

            return {
                "prs": [self._serialize_row(r) for r in all_prs],
                "prs_detail": [self._serialize_row(r) for r in all_detail],
                "jadwal_ss": [self._serialize_row(r) for r in all_jadwal],
                "kelas_config": [self._serialize_row(r) for r in all_config],
            }
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _get_kapasitas(self, cur, id_kelas):
        """
        Fetch kelas capacity from kelas_config.
        Falls back to DEFAULT_KAPASITAS if not configured.

        TODO: When Penawaran Kelas exposes kapasitas via RPC, sync it into
        kelas_config at enrollment time (similar to how jadwal_ss is populated).
        """
        cur.execute(
            "SELECT kapasitas FROM kelas_config WHERE id_kelas = %s",
            (id_kelas,),
        )
        row = cur.fetchone()
        return row["kapasitas"] if row else DEFAULT_KAPASITAS

    @staticmethod
    def _serialize_row(row):
        """Convert datetime/timedelta values to JSON-safe strings."""
        out = {}
        for k, v in row.items():
            if isinstance(v, (datetime, date)):
                out[k] = v.isoformat()
            elif isinstance(v, timedelta):
                out[k] = str(v)
            else:
                out[k] = v
        return out