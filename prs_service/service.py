"""
service.py — Nameko RPC microservice for PRS (Pembuatan Rencana Studi).

Tables owned:
    prs         — header per mahasiswa per semester
    prs_detail  — kelas yang diambil, with prioritas & status_validasi
    jadwal_ss   — snapshot jadwal from Penawaran Kelas at enrollment time

Exposed RPC methods (mapped from function matrix):
    1. create_prs               — insert PRS header (status=draft)
    2. create_prs_detail        — insert one kelas into a PRS
    3. get_prs                  — fetch PRS header by id_mahasiswa + id_semester
    4. get_prs_detail_by_semester  — all details for a given semester
    5. get_prs_detail_by_prs_id    — all details for a given id_prs
    6. get_prs_detail_by_kelas_id  — all details for a given id_kelas (across all PRS)
    7. get_jumlah_mahasiswa_per_kelas — count students enrolled per kelas
    8. verify_prs               — approve/reject detail lines + add comment, update total_sks
    9. push_peserta_to_transkrip — mark validated PRS details as finalized (triggers transkrip)
    10. snapshot_jadwal          — snapshot jadwal from Penawaran Kelas into jadwal_ss
    11. sync_jadwal_snapshot      — update jadwal_ss when Penawaran Kelas notifies of jadwal change
    12. debug_dump               — dump all PRS + details + jadwal_ss
"""

import os
import logging

import pymysql
from nameko.rpc import rpc, RpcProxy
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PRSService:
    """PRS microservice. All RPC methods return plain dicts / lists."""

    name = "prs_service"

    # NOTE: This proxy is currently UNUSED for real calls — create_prs_detail
    # uses dummy jadwal data (see TODO there) until Penawaran Kelas exposes
    # its jadwal-fetching RPC method. Once available, swap the dummy block
    # in create_prs_detail for a call to self.penawaran_kelas_rpc.<method_name>.
    penawaran_kelas_rpc = RpcProxy("penawaran_kelas_service")

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
    # 2. Create PRS_Detail
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
                # Guard: PRS must be in draft
                cur.execute(
                    "SELECT status FROM prs WHERE id_prs = %s FOR UPDATE",
                    (id_prs,),
                )
                prs = cur.fetchone()
                if not prs:
                    return {"error": "PRS tidak ditemukan"}
                if prs["status"] != "draft":
                    return {"error": f"PRS status '{prs['status']}', hanya bisa tambah kelas saat draft"}

                # Guard: prioritas must be 1, 2, or 3
                if prioritas not in (1, 2, 3):
                    return {"error": "Prioritas harus 1, 2, atau 3"}

                cur.execute(
                    """INSERT INTO prs_detail
                           (id_prs, id_kelas, id_mata_kuliah, prioritas, sks, status_validasi)
                       VALUES (%s, %s, %s, %s, %s, 'pending')""",
                    (id_prs, id_kelas, id_mata_kuliah, prioritas, sks),
                )
                id_detail = cur.lastrowid

                # ------------------------------------------------------------
                # DUMMY DATA — jadwal snapshot at enrollment time
                # ------------------------------------------------------------
                # TODO: This is placeholder data. Once Penawaran Kelas exposes
                # its RPC method (e.g. get_jadwal_by_kelas), replace the line
                # below with:
                #
                #     jadwal_list = self.penawaran_kelas_rpc.get_jadwal_by_kelas(id_kelas)
                #
                # Make sure the dicts returned have the keys expected by
                # _snapshot_jadwal: id_jadwal, hari, jam_mulai, jam_selesai,
                # ruangan, tipe.
                jadwal_list = [
                    {
                        "id_jadwal": id_kelas * 1000 + 1,  # dummy unique id
                        "hari": "Senin",
                        "jam_mulai": "08:00:00",
                        "jam_selesai": "09:40:00",
                        "ruangan": "DUMMY-ROOM",
                        "tipe": "teori",
                    }
                ]
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
    # 3. Fetch PRS
    # -----------------------------------------------------------------------

    @rpc
    def get_prs(self, id_mahasiswa, id_semester):
        """
        Fetch PRS header for a given mahasiswa + semester.
        Returns the PRS row including status and total_sks.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT * FROM prs
                       WHERE id_mahasiswa = %s AND id_semester = %s""",
                    (id_mahasiswa, id_semester),
                )
                row = cur.fetchone()
                if not row:
                    return {"error": "PRS tidak ditemukan"}
                return row
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 4. Fetch PRS_Detail by semester_id
    # -----------------------------------------------------------------------

    @rpc
    def get_prs_detail_by_semester(self, id_semester):
        """
        Fetch all PRS_Detail rows for an entire semester.
        Useful for dosen wali to see all student enrollments in one semester.
        """
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
                return cur.fetchall()
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 5. Fetch PRS_Detail by prs_id
    # -----------------------------------------------------------------------

    @rpc
    def get_prs_detail_by_prs_id(self, id_prs):
        """
        Fetch all detail lines for a single PRS (one student, one semester).
        """
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
                return rows
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 6. Fetch PRS_Detail by kelas_id
    # -----------------------------------------------------------------------

    @rpc
    def get_prs_detail_by_kelas_id(self, id_kelas):
        """
        Fetch all PRS_Detail rows for a given kelas across all students.
        Used to check who has enrolled in a specific kelas.
        """
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
                return cur.fetchall()
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 7. Fetch Jumlah Mahasiswa per kelas
    # -----------------------------------------------------------------------

    @rpc
    def get_jumlah_mahasiswa_per_kelas(self, id_kelas=None):
        """
        Count enrolled students per kelas.
        - If id_kelas is given: returns count for that specific kelas.
        - If not given: returns count for ALL kelas (useful for capacity checks).
        Only counts rows with status_validasi='approved'.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                if id_kelas:
                    cur.execute(
                        """SELECT id_kelas,
                                  COUNT(*) AS jumlah_mahasiswa
                           FROM prs_detail
                           WHERE id_kelas = %s AND status_validasi = 'approved'
                           GROUP BY id_kelas""",
                        (id_kelas,),
                    )
                    row = cur.fetchone()
                    return row if row else {"id_kelas": id_kelas, "jumlah_mahasiswa": 0}
                else:
                    cur.execute(
                        """SELECT id_kelas,
                                  COUNT(*) AS jumlah_mahasiswa
                           FROM prs_detail
                           WHERE status_validasi = 'approved'
                           GROUP BY id_kelas
                           ORDER BY id_kelas"""
                    )
                    return cur.fetchall()
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 8. Verify PRS (approve / reject detail lines, add comment)
    # -----------------------------------------------------------------------

    @rpc
    def verify_prs(self, id_prs, verifikasi, komentar=None):
        """
        Dosen wali verifies a PRS by approving/rejecting individual detail lines.

        id_prs      : int
        verifikasi  : list of dicts, e.g.:
                      [
                        {"id_detail_prs": 1, "status_validasi": "approved"},
                        {"id_detail_prs": 2, "status_validasi": "rejected"},
                      ]
        komentar    : optional string comment stored on the PRS header

        Logic:
          - Each detail line gets its status_validasi updated.
          - PRS.total_sks is recalculated from approved lines only.
          - PRS.status is set to 'validated' if at least one line is approved,
            otherwise remains 'process'.
        """
        if not verifikasi or not isinstance(verifikasi, list):
            return {"error": "Parameter verifikasi harus berupa list"}

        db = self._db()
        try:
            with db.cursor() as cur:
                # Ensure PRS exists and is in 'process'
                cur.execute(
                    "SELECT * FROM prs WHERE id_prs = %s FOR UPDATE",
                    (id_prs,),
                )
                prs = cur.fetchone()
                if not prs:
                    return {"error": "PRS tidak ditemukan"}
                if prs["status"] not in ("process", "draft"):
                    return {"error": f"PRS status '{prs['status']}', tidak bisa diverifikasi"}

                # Update each detail line
                for item in verifikasi:
                    sv = item.get("status_validasi")
                    if sv not in ("approved", "rejected", "pending"):
                        return {"error": f"status_validasi tidak valid: {sv}"}
                    cur.execute(
                        """UPDATE prs_detail
                           SET status_validasi = %s
                           WHERE id_detail_prs = %s AND id_prs = %s""",
                        (sv, item["id_detail_prs"], id_prs),
                    )

                # Recalculate total_sks from approved lines
                cur.execute(
                    """SELECT COALESCE(SUM(sks), 0) AS total
                       FROM prs_detail
                       WHERE id_prs = %s AND status_validasi = 'approved'""",
                    (id_prs,),
                )
                total_sks = cur.fetchone()["total"]

                # Determine new PRS status
                cur.execute(
                    """SELECT COUNT(*) AS cnt FROM prs_detail
                       WHERE id_prs = %s AND status_validasi = 'approved'""",
                    (id_prs,),
                )
                has_approved = cur.fetchone()["cnt"] > 0
                new_status = "validated" if has_approved else "process"

                cur.execute(
                    """UPDATE prs
                       SET status = %s, total_sks = %s
                       WHERE id_prs = %s""",
                    (new_status, total_sks, id_prs),
                )

            db.commit()
            return {
                "message": "Verifikasi PRS berhasil",
                "id_prs": id_prs,
                "status": new_status,
                "total_sks": total_sks,
                "komentar": komentar,
            }
        except pymysql.Error as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 9. Push peserta to transkrip
    # -----------------------------------------------------------------------

    @rpc
    def push_peserta_to_transkrip(self, id_semester):
        """
        Collect all validated PRS details for a semester and return them
        as a list ready to be pushed to the Transkrip service.

        Only returns details where:
          - prs.status = 'validated'
          - prs_detail.status_validasi = 'approved'

        The Transkrip service is responsible for consuming this data.
        This method only reads (R) from prs + prs_detail; the actual
        write to transkrip happens in the Transkrip service via RPC.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT
                           p.id_mahasiswa,
                           p.id_semester,
                           pd.id_kelas,
                           pd.id_mata_kuliah,
                           pd.sks,
                           pd.status_validasi
                       FROM prs_detail pd
                       JOIN prs p ON pd.id_prs = p.id_prs
                       WHERE p.id_semester = %s
                         AND p.status = 'validated'
                         AND pd.status_validasi = 'approved'
                       ORDER BY p.id_mahasiswa, pd.id_mata_kuliah""",
                    (id_semester,),
                )
                peserta = cur.fetchall()

            if not peserta:
                return {"error": "Tidak ada peserta validated untuk semester ini"}

            return {
                "message": f"{len(peserta)} peserta siap dipush ke transkrip",
                "id_semester": id_semester,
                "peserta": peserta,
            }
        finally:
            db.close()
            

    # -----------------------------------------------------------------------
    # 10. Snapshot jadwal into jadwal_ss (called inside create_prs_detail)
    # -----------------------------------------------------------------------

    def _snapshot_jadwal(self, db, id_detail_prs, jadwal_list):
        """
        Internal helper — snapshots jadwal from Penawaran Kelas into jadwal_ss.
        jadwal_list: list of dicts with keys:
            id_jadwal, hari, jam_mulai, jam_selesai, ruangan, tipe
        """
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
        """
        Public RPC wrapper around _snapshot_jadwal.
        Called by Penawaran Kelas when a new jadwal is created.
        """
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
    # 11. Sync jadwal snapshot (called when Penawaran Kelas updates a jadwal)
    # -----------------------------------------------------------------------

    @rpc
    def sync_jadwal_snapshot(self, id_detail_prs, jadwal_list):
        """
        Updates jadwal_ss when Penawaran Kelas notifies of a jadwal change.
        Edits existing rows in-place using id_jadwal as the stable key.
        Removes rows that no longer exist in the new jadwal_list.

        jadwal_list: list of dicts with keys:
            id_jadwal, hari, jam_mulai, jam_selesai, ruangan, tipe
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                incoming_ids = [j["id_jadwal"] for j in jadwal_list]

                # Remove rows that are no longer in the new jadwal_list
                if incoming_ids:
                    placeholders = ",".join(["%s"] * len(incoming_ids))
                    cur.execute(
                        f"DELETE FROM jadwal_ss WHERE id_detail_prs = %s AND id_jadwal NOT IN ({placeholders})",
                        [id_detail_prs, *incoming_ids],
                    )
                else:
                    # No jadwal at all — wipe everything for this detail
                    cur.execute(
                        "DELETE FROM jadwal_ss WHERE id_detail_prs = %s",
                        (id_detail_prs,),
                    )

                for j in jadwal_list:
                    cur.execute(
                        """UPDATE jadwal_ss
                               SET jam_mulai   = %s,
                                   jam_selesai = %s,
                                   hari        = %s,
                                   ruangan     = %s,
                                   tipe        = %s,
                                   is_outdated = 0
                           WHERE id_jadwal = %s AND id_detail_prs = %s""",
                        (
                            j["jam_mulai"],
                            j["jam_selesai"],
                            j["hari"],
                            j["ruangan"],
                            j["tipe"],
                            j["id_jadwal"],
                            id_detail_prs,
                        ),
                    )
                    if cur.rowcount == 0:  # Row didn't exist — insert fresh
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

            db.commit()
            return {"message": "Jadwal snapshot updated", "id_detail_prs": id_detail_prs}
        except Exception as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # 12. Debug — dump all PRS, PRS_Detail, and Jadwal_SS
    # -----------------------------------------------------------------------

    @rpc
    def debug_dump(self):
        """
        Returns all rows from prs, prs_detail, and jadwal_ss as separate tables.
        For debugging only — do not expose in production.
        """
        db = self._db()
        try:
            with db.cursor() as cur:
                cur.execute("SELECT * FROM prs ORDER BY id_prs")
                all_prs = cur.fetchall()

                cur.execute("SELECT * FROM prs_detail ORDER BY id_prs, id_detail_prs")
                all_detail = cur.fetchall()

                cur.execute("SELECT * FROM jadwal_ss ORDER BY id_detail_prs, id_jadwal_ss")
                all_jadwal = cur.fetchall()

            return {
                "prs": [self._serialize_row(r) for r in all_prs],
                "prs_detail": [self._serialize_row(r) for r in all_detail],
                "jadwal_ss": [self._serialize_row(r) for r in all_jadwal],
            }
        finally:
            db.close()

    @staticmethod
    def _serialize_row(row):
        """Convert datetime/timedelta values in a row dict to JSON-safe strings."""
        out = {}
        for k, v in row.items():
            if isinstance(v, (datetime, date)):
                out[k] = v.isoformat()
            elif isinstance(v, timedelta):
                out[k] = str(v)  # e.g. "8:00:00"
            else:
                out[k] = v
        return out