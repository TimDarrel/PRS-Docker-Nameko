"""
gateway.py — HTTP gateway for the PRS microservice.

Routes:
  GET    /health
  POST   /prs                                        → create_prs
  POST   /prs/<id_prs>/detail                        → create_prs_detail
  GET    /prs/<id_mahasiswa>/<id_semester>           → get_prs
  GET    /prs/detail/<id_semester>                   → get_prs_detail_by_semester
  GET    /prs/<id_prs>/detail                        → get_prs_detail_by_prs_id
  GET    /prs/detail/kelas/<id_kelas>                → get_prs_detail_by_kelas_id
  GET    /prs/kelas/<id_kelas>/jumlah                → get_jumlah_mahasiswa_per_kelas
  GET    /prs/kelas/jumlah                           → get_jumlah_mahasiswa_per_kelas (all)
  PUT    /prs/<id_prs>/verify                        → verify_prs          (single student, auto)
  PUT   /prs/semester/<id_semester>/verify           → verify_prs_by_semester (whole semester)
  POST   /prs/transkrip/<id_semester>                → push_peserta_to_transkrip
  PUT    /prs/jadwal/invalidate/<id_kelas>           → invalidate_jadwal
  POST   /prs/detail/<id_detail_prs>/jadwal/snapshot → snapshot_jadwal
  POST   /prs/jadwal/snapshot/<id_detail_prs>        → sync_jadwal_snapshot
  GET    /debug/dump                                 → debug_dump
"""

import json
from datetime import datetime, date
from nameko.rpc import RpcProxy
from nameko.web.handlers import http


def dumps(data):
    def default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    return json.dumps(data, default=default)


class GatewayService:
    name = "gateway_service"

    prs_rpc = RpcProxy("prs_service")

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @http("GET", "/health")
    def health(self, request):
        return json.dumps({"status": "ok"})

    # -----------------------------------------------------------------------
    # 1. Create PRS
    # POST /prs
    # -----------------------------------------------------------------------

    @http("POST", "/prs")
    def create_prs(self, request):
        body = json.loads(request.get_data(as_text=True) or "{}")
        required = ["id_mahasiswa", "id_semester", "dosen_wali_id"]
        missing = [f for f in required if f not in body]
        if missing:
            return 400, json.dumps({"success": False, "error": f"Field wajib: {', '.join(missing)}"})

        result = self.prs_rpc.create_prs(
            body["id_mahasiswa"],
            body["id_semester"],
            body["dosen_wali_id"],
        )
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return 201, json.dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 2. Create PRS Detail
    # POST /prs/<id_prs>/detail
    # -----------------------------------------------------------------------

    @http("POST", "/prs/<int:id_prs>/detail")
    def create_prs_detail(self, request, id_prs):
        body = json.loads(request.get_data(as_text=True) or "{}")
        required = ["id_kelas", "id_mata_kuliah", "sks"]
        missing = [f for f in required if f not in body]
        if missing:
            return 400, json.dumps({"success": False, "error": f"Field wajib: {', '.join(missing)}"})

        result = self.prs_rpc.create_prs_detail(
            id_prs=id_prs,
            id_kelas=body["id_kelas"],
            id_mata_kuliah=body["id_mata_kuliah"],
            sks=body["sks"],
            prioritas=body.get("prioritas", 1),
        )
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return 201, json.dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 3. Get PRS
    # GET /prs/<id_mahasiswa>/<id_semester>
    # -----------------------------------------------------------------------

    @http("GET", "/prs/<int:id_mahasiswa>/<int:id_semester>")
    def get_prs(self, request, id_mahasiswa, id_semester):
        result = self.prs_rpc.get_prs(id_mahasiswa, id_semester)
        if "error" in result:
            return 404, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 4. Get PRS Detail by semester
    # GET /prs/detail/<int:id_semester>
    # -----------------------------------------------------------------------

    @http("GET", "/prs/detail/<int:id_semester>")
    def get_prs_detail_by_semester(self, request, id_semester):
        result = self.prs_rpc.get_prs_detail_by_semester(id_semester)
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 5. Get PRS Detail by prs_id
    # GET /prs/<id_prs>/detail
    # -----------------------------------------------------------------------

    @http("GET", "/prs/<int:id_prs>/detail")
    def get_prs_detail_by_prs_id(self, request, id_prs):
        result = self.prs_rpc.get_prs_detail_by_prs_id(id_prs)
        if isinstance(result, dict) and "error" in result:
            return 404, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 6. Get PRS Detail by kelas
    # GET /prs/detail/kelas/<id_kelas>
    # -----------------------------------------------------------------------

    @http("GET", "/prs/detail/kelas/<int:id_kelas>")
    def get_prs_detail_by_kelas_id(self, request, id_kelas):
        result = self.prs_rpc.get_prs_detail_by_kelas_id(id_kelas)
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 7. Jumlah mahasiswa per kelas
    # GET /prs/kelas/<id_kelas>/jumlah
    # GET /prs/kelas/jumlah
    # -----------------------------------------------------------------------

    @http("GET", "/prs/kelas/<int:id_kelas>/jumlah")
    def get_jumlah_per_kelas(self, request, id_kelas):
        result = self.prs_rpc.get_jumlah_mahasiswa_per_kelas(id_kelas=id_kelas)
        return dumps({"success": True, "data": result})

    @http("GET", "/prs/kelas/jumlah")
    def get_jumlah_all_kelas(self, request):
        result = self.prs_rpc.get_jumlah_mahasiswa_per_kelas()
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 8. Verify single PRS (auto)
    # PUT /prs/<id_prs>/verify
    #
    # PUT because this is an idempotent update to an existing resource.
    # Running it twice produces the same result — correct PUT semantics.
    # No request body needed; all logic is driven by existing DB state.
    # -----------------------------------------------------------------------

    @http("PUT", "/prs/<int:id_prs>/verify")
    def verify_prs(self, request, id_prs):
        result = self.prs_rpc.verify_prs(id_prs=id_prs)
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 9. Verify all PRS in a semester (auto, shared capacity pool)
    # PUT /prs/semester/<id_semester>/verify
    #
    # PUT because this is a bulk operation that triggers a significant
    # state transition across many resources — not idempotent (running it
    # twice after changes would re-evaluate changed state).
    # -----------------------------------------------------------------------

    @http("PUT", "/prs/semester/<int:id_semester>/verify")
    def verify_prs_by_semester(self, request, id_semester):
        result = self.prs_rpc.verify_prs_by_semester(id_semester=id_semester)
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 10. Push peserta to transkrip
    # POST /prs/transkrip/<id_semester>
    # -----------------------------------------------------------------------

    @http("POST", "/prs/transkrip/<int:id_semester>")
    def push_peserta_to_transkrip(self, request, id_semester):
        result = self.prs_rpc.push_peserta_to_transkrip(id_semester)
        if "error" in result:
            return 404, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})
    
    # -----------------------------------------------------------------------
    # 11. Invalidate jadwal snapshot
    # PUT /prs/jadwal/invalidate/<int:id_kelas>
    # -----------------------------------------------------------------------
    
    @http("PUT", "/prs/jadwal/invalidate/<int:id_kelas>")
    def invalidate_jadwal(self, request, id_kelas):
        result = self.prs_rpc.invalidate_jadwal_snapshot(id_kelas=id_kelas)
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 12. Snapshot jadwal
    # POST /prs/detail/<id_detail_prs>/jadwal/snapshot
    # -----------------------------------------------------------------------

    @http("POST", "/prs/detail/<int:id_detail_prs>/jadwal/snapshot")
    def snapshot_jadwal(self, request, id_detail_prs):
        body = json.loads(request.get_data(as_text=True) or "{}")

        if "jadwal" not in body:
            return 400, json.dumps({"success": False, "error": "Field jadwal (list) wajib diisi"})

        jadwal_list = body["jadwal"]
        if not isinstance(jadwal_list, list):
            return 400, json.dumps({"success": False, "error": "Field jadwal harus berupa list"})

        required_keys = {"id_jadwal", "hari", "jam_mulai", "jam_selesai", "ruangan", "tipe"}
        for i, j in enumerate(jadwal_list):
            missing = required_keys - j.keys()
            if missing:
                return 400, json.dumps({
                    "success": False,
                    "error": f"Jadwal index {i} kekurangan field: {', '.join(missing)}"
                })

        result = self.prs_rpc.snapshot_jadwal(
            id_detail_prs=id_detail_prs,
            jadwal_list=jadwal_list,
        )
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return 201, dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 13. Sync jadwal snapshot
    # POST /prs/jadwal/snapshot/<id_detail_prs>
    # -----------------------------------------------------------------------

    @http("POST", "/prs/jadwal/snapshot/<int:id_detail_prs>")
    def sync_jadwal_snapshot(self, request, id_detail_prs):
        body = json.loads(request.get_data(as_text=True) or "{}")

        if "jadwal" not in body:
            return 400, json.dumps({"success": False, "error": "Field jadwal (list) wajib diisi"})

        jadwal_list = body["jadwal"]
        if not isinstance(jadwal_list, list):
            return 400, json.dumps({"success": False, "error": "Field jadwal harus berupa list"})

        required_keys = {"id_jadwal", "hari", "jam_mulai", "jam_selesai", "ruangan", "tipe"}
        for i, j in enumerate(jadwal_list):
            missing = required_keys - j.keys()
            if missing:
                return 400, json.dumps({
                    "success": False,
                    "error": f"Jadwal index {i} kekurangan field: {', '.join(missing)}"
                })

        result = self.prs_rpc.sync_jadwal_snapshot(
            id_detail_prs=id_detail_prs,
            jadwal_list=jadwal_list,
        )
        if "error" in result:
            return 400, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})
    
    # GET /prs/detail/<id_detail_prs>/jadwal
    @http("GET", "/prs/detail/<int:id_detail_prs>/jadwal")
    def get_jadwal_by_detail(self, request, id_detail_prs):
        result = self.prs_rpc.get_jadwal_by_detail(id_detail_prs=id_detail_prs)
        return dumps({"success": True, "data": result})

    # GET /prs/<id_prs>/jadwal  ← full schedule for one student's PRS
    @http("GET", "/prs/<int:id_prs>/jadwal")
    def get_jadwal_by_prs(self, request, id_prs):
        result = self.prs_rpc.get_jadwal_by_prs(id_prs=id_prs)
        return dumps({"success": True, "data": result})

    # -----------------------------------------------------------------------
    # 14. Debug dump
    # GET /debug/dump
    # -----------------------------------------------------------------------

    @http("GET", "/debug/dump")
    def debug_dump(self, request):
        result = self.prs_rpc.debug_dump()
        if "error" in result:
            return 500, json.dumps({"success": False, "error": result["error"]})
        return dumps({"success": True, "data": result})