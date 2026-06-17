-- ============================================================
-- PRS Database Schema + Rich Seed Data
-- Designed to test: priority fallthrough, capacity limits, SKS cap
-- ============================================================

CREATE DATABASE IF NOT EXISTS prs_db;
USE prs_db;

-- ----------------------------------------------------------
-- Tables
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS prs (
    id_prs          INT AUTO_INCREMENT PRIMARY KEY,
    id_mahasiswa    INT          NOT NULL,
    id_semester     INT          NOT NULL,
    dosen_wali_id   INT          NOT NULL,
    status          ENUM('draft', 'process', 'validated') NOT NULL DEFAULT 'draft',
    total_sks       INT          NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_prs (id_mahasiswa, id_semester)
);

CREATE TABLE IF NOT EXISTS prs_detail (
    id_detail_prs   INT AUTO_INCREMENT PRIMARY KEY,
    id_prs          INT          NOT NULL,
    id_kelas        INT          NOT NULL,
    id_mata_kuliah  INT          NOT NULL,
    prioritas       TINYINT      NOT NULL DEFAULT 1,
    sks             INT          NOT NULL,
    status_validasi ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_detail (id_prs, id_kelas),
    FOREIGN KEY (id_prs) REFERENCES prs(id_prs) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jadwal_ss (
    id_jadwal_ss    INT AUTO_INCREMENT PRIMARY KEY,
    id_jadwal       INT          NOT NULL,
    id_detail_prs   INT          NOT NULL,
    jam_mulai       TIME         NOT NULL,
    jam_selesai     TIME         NOT NULL,
    hari            VARCHAR(20)  NOT NULL,
    ruangan         VARCHAR(50)  NOT NULL,
    tipe            ENUM('teori', 'praktikum') NOT NULL,
    is_outdated     TINYINT(1)   NOT NULL DEFAULT 0,
    snapshotted_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_detail_prs) REFERENCES prs_detail(id_detail_prs) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- NEW: kelas_config — kapasitas per kelas
-- Default kapasitas = 40 (overridden per kelas as needed).
-- Future: sync from Penawaran Kelas via RPC into this table.
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS kelas_config (
    id_kelas    INT PRIMARY KEY,
    kapasitas   INT NOT NULL DEFAULT 40,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ============================================================
-- SEED DATA
--
-- Semester 1: already-validated PRS (baseline, don't re-verify)
-- Semester 2: the interesting semester for testing verification
--
-- Semester 2 scenarios built into the data:
--
--  Mahasiswa 10 (id_prs=4):
--    MK-A: prioritas 1 → kelas 201 (available)            → APPROVED p1
--    MK-B: prioritas 1 → kelas 202 (available)            → APPROVED p1
--    MK-C: prioritas 1 → kelas 203 (available)            → APPROVED p1
--    = 9 SKS total. Simple happy path.
--
--  Mahasiswa 11 (id_prs=5):
--    MK-A: prioritas 1 → kelas 201, prioritas 2 → kelas 204
--          kelas 201 is set to kapasitas=1, already taken by mhs 10
--          → falls through to kelas 204                   → APPROVED p2
--    MK-D: prioritas 1 → kelas 205 (available)            → APPROVED p1
--    MK-E: prioritas 1 → kelas 206 (available)            → APPROVED p1
--    = 9 SKS. Tests capacity fallthrough.
--
--  Mahasiswa 12 (id_prs=6):
--    MK-F: 6 SKS, prioritas 1 → kelas 207                 → APPROVED p1
--    MK-G: 6 SKS, prioritas 1 → kelas 208                 → APPROVED p1
--    MK-H: 6 SKS, prioritas 1 → kelas 209                 → APPROVED p1
--    MK-I: 6 SKS, prioritas 1 → kelas 210                 → REJECTED (would hit 24 SKS cap)
--    = 18 SKS approved, MK-I rejected. Tests SKS cap.
--
--  Mahasiswa 13 (id_prs=7):
--    MK-A: p1 → kelas 201 (full after mhs 10), p2 → kelas 204 (full after mhs 11),
--           p3 → kelas 211 (available)                    → APPROVED p3
--    MK-J: p1 → kelas 212 (available)                     → APPROVED p1
--    = 6 SKS. Tests full priority chain p1→p2→p3.
--
--  Mahasiswa 14 (id_prs=8):
--    MK-K: p1 → kelas 213 (kapasitas=0, intentionally full) → REJECTED all
--    No fallback prioritas. Tests all-rejected path.
-- ============================================================

-- ----------------------------------------------------------
-- kelas_config seed
-- Most kelas default to 40 seats; a few are constrained for testing.
-- ----------------------------------------------------------
INSERT INTO kelas_config (id_kelas, kapasitas) VALUES
(201, 1),   -- only 1 seat: taken by mhs 10 → mhs 11 falls to p2, mhs 13 falls to p3
(204, 1),   -- only 1 seat: taken by mhs 11 → mhs 13 falls to p3
(213, 0),   -- no seats at all → mhs 14's MK-K is fully rejected
(202, 40),
(203, 40),
(205, 40),
(206, 40),
(207, 40),
(208, 40),
(209, 40),
(210, 40),
(211, 40),
(212, 40);

-- ----------------------------------------------------------
-- Semester 1 — already validated, used as baseline
-- ----------------------------------------------------------
INSERT INTO prs (id_mahasiswa, id_semester, dosen_wali_id, status, total_sks) VALUES
(1, 1, 10, 'validated', 18),
(2, 1, 10, 'validated', 15),
(3, 1, 11, 'validated', 18);

INSERT INTO prs_detail (id_prs, id_kelas, id_mata_kuliah, prioritas, sks, status_validasi) VALUES
-- mhs 1
(1, 101, 1, 1, 3, 'approved'),
(1, 102, 2, 1, 3, 'approved'),
(1, 103, 3, 1, 3, 'approved'),
(1, 104, 4, 1, 3, 'approved'),
(1, 105, 5, 1, 3, 'approved'),
(1, 106, 6, 1, 3, 'approved'),
-- mhs 2
(2, 107, 1, 1, 3, 'approved'),
(2, 108, 2, 1, 3, 'approved'),
(2, 109, 3, 1, 3, 'approved'),
(2, 110, 4, 1, 3, 'approved'),
(2, 111, 5, 1, 3, 'approved'),
-- mhs 3
(3, 112, 7, 1, 3, 'approved'),
(3, 113, 8, 1, 3, 'approved'),
(3, 114, 9, 1, 3, 'approved'),
(3, 115, 10, 1, 3, 'approved'),
(3, 116, 11, 1, 3, 'approved'),
(3, 117, 12, 1, 3, 'approved');

-- ----------------------------------------------------------
-- Semester 2 — the verification test semester
-- Status is 'draft' so verify_prs / verify_prs_by_semester
-- will pick them up.
-- ----------------------------------------------------------
INSERT INTO prs (id_mahasiswa, id_semester, dosen_wali_id, status, total_sks) VALUES
(10, 2, 20, 'draft', 0),  -- id_prs=4: happy path
(11, 2, 20, 'draft', 0),  -- id_prs=5: capacity fallthrough p1→p2
(12, 2, 20, 'draft', 0),  -- id_prs=6: SKS cap (24 SKS limit)
(13, 2, 21, 'draft', 0),  -- id_prs=7: full priority chain p1→p2→p3
(14, 2, 21, 'draft', 0);  -- id_prs=8: all rejected (kelas full, no fallback)

INSERT INTO prs_detail (id_prs, id_kelas, id_mata_kuliah, prioritas, sks, status_validasi) VALUES

-- ── id_prs=4, mhs 10: happy path ─────────────────────────────────────────
-- MK-A (mk=1): only p1
(4, 201, 1, 1, 3, 'pending'),
-- MK-B (mk=2): only p1
(4, 202, 2, 1, 3, 'pending'),
-- MK-C (mk=3): only p1
(4, 203, 3, 1, 3, 'pending'),

-- ── id_prs=5, mhs 11: capacity fallthrough p1→p2 ─────────────────────────
-- MK-A (mk=1): p1=kelas 201 (cap=1, full after mhs 10), p2=kelas 204 (cap=1, available)
(5, 201, 1, 1, 3, 'pending'),
(5, 204, 1, 2, 3, 'pending'),
-- MK-D (mk=4): p1 only
(5, 205, 4, 1, 3, 'pending'),
-- MK-E (mk=5): p1 only
(5, 206, 5, 1, 3, 'pending'),

-- ── id_prs=6, mhs 12: SKS cap test ───────────────────────────────────────
-- MK-F (mk=6): 6 SKS p1                → running total: 6
(6, 207, 6, 1, 6, 'pending'),
-- MK-G (mk=7): 6 SKS p1                → running total: 12
(6, 208, 7, 1, 6, 'pending'),
-- MK-H (mk=8): 6 SKS p1                → running total: 18
(6, 209, 8, 1, 6, 'pending'),
-- MK-I (mk=9): 6 SKS p1 → would hit 24 → REJECTED (18+6=24 is ok actually; let's make it 7)
-- Note: 18 + 7 = 25 > MAX_SKS(24) → rejected
(6, 210, 9, 1, 7, 'pending'),

-- ── id_prs=7, mhs 13: full p1→p2→p3 chain ───────────────────────────────
-- MK-A (mk=1): p1=kelas 201 (full), p2=kelas 204 (full after mhs 11), p3=kelas 211 (free)
(7, 201, 1, 1, 3, 'pending'),
(7, 204, 1, 2, 3, 'pending'),
(7, 211, 1, 3, 3, 'pending'),
-- MK-J (mk=10): p1 only
(7, 212, 10, 1, 3, 'pending'),

-- ── id_prs=8, mhs 14: all rejected ───────────────────────────────────────
-- MK-K (mk=11): p1=kelas 213 (kapasitas=0), no fallback
(8, 213, 11, 1, 3, 'pending');

-- ----------------------------------------------------------
-- Jadwal_SS seed for semester 1 (historical, already validated)
-- ----------------------------------------------------------
INSERT INTO jadwal_ss (id_jadwal, id_detail_prs, jam_mulai, jam_selesai, hari, ruangan, tipe, is_outdated) VALUES
(1001, 1,  '08:00', '09:40', 'Senin',   'GKB1-101', 'teori', 0),
(1002, 2,  '10:00', '11:40', 'Selasa',  'GKB1-102', 'teori', 0),
(1003, 3,  '13:00', '14:40', 'Rabu',    'GKB1-103', 'teori', 0),
(1004, 4,  '08:00', '09:40', 'Kamis',   'GKB1-104', 'teori', 0),
(1005, 5,  '10:00', '11:40', 'Jumat',   'GKB1-105', 'teori', 0),
(1006, 6,  '13:00', '14:40', 'Senin',   'GKB2-101', 'teori', 0),
(1007, 7,  '08:00', '09:40', 'Selasa',  'GKB2-102', 'teori', 0),
(1008, 8,  '10:00', '11:40', 'Rabu',    'GKB2-103', 'teori', 0),
(1009, 9,  '13:00', '14:40', 'Kamis',   'GKB2-104', 'teori', 0),
(1010, 10, '08:00', '09:40', 'Jumat',   'GKB2-105', 'teori', 0),
(1011, 11, '10:00', '11:40', 'Senin',   'GKB2-106', 'teori', 0),
(1012, 12, '08:00', '09:40', 'Selasa',  'GKB3-101', 'teori', 0),
(1013, 13, '10:00', '11:40', 'Rabu',    'GKB3-102', 'teori', 0),
(1014, 14, '13:00', '14:40', 'Kamis',   'GKB3-103', 'teori', 0),
(1015, 15, '08:00', '09:40', 'Jumat',   'GKB3-104', 'teori', 0),
(1016, 16, '10:00', '11:40', 'Senin',   'LAB-01',   'praktikum', 0),
(1017, 17, '13:00', '14:40', 'Selasa',  'LAB-02',   'praktikum', 0);

-- ----------------------------------------------------------
-- Jadwal_SS seed for semester 2 (pending PRS — dummy snapshots,
-- matching the dummy data created by create_prs_detail)
-- id_detail_prs 18..33 correspond to the prs_detail rows above.
-- ----------------------------------------------------------
INSERT INTO jadwal_ss (id_jadwal, id_detail_prs, jam_mulai, jam_selesai, hari, ruangan, tipe, is_outdated) VALUES
-- prs=4, mhs 10
(2010, 18, '08:00', '09:40', 'Senin',   'GKB1-201', 'teori', 0),  -- kelas 201
(2020, 19, '10:00', '11:40', 'Selasa',  'GKB1-202', 'teori', 0),  -- kelas 202
(2030, 20, '13:00', '14:40', 'Rabu',    'GKB1-203', 'teori', 0),  -- kelas 203

-- prs=5, mhs 11
(2010, 21, '08:00', '09:40', 'Senin',   'GKB1-201', 'teori', 0),  -- kelas 201 (p1, will be rejected)
(2040, 22, '08:00', '09:40', 'Senin',   'GKB1-204', 'teori', 0),  -- kelas 204 (p2, will be approved)
(2050, 23, '10:00', '11:40', 'Kamis',   'GKB1-205', 'teori', 0),  -- kelas 205
(2060, 24, '13:00', '14:40', 'Jumat',   'GKB1-206', 'teori', 0),  -- kelas 206

-- prs=6, mhs 12
(2070, 25, '08:00', '10:40', 'Senin',   'GKB2-201', 'teori', 0),  -- kelas 207 (6 SKS)
(2080, 26, '11:00', '13:40', 'Selasa',  'GKB2-202', 'teori', 0),  -- kelas 208 (6 SKS)
(2090, 27, '14:00', '16:40', 'Rabu',    'GKB2-203', 'teori', 0),  -- kelas 209 (6 SKS)
(2100, 28, '08:00', '10:40', 'Kamis',   'GKB2-204', 'teori', 0),  -- kelas 210 (7 SKS, rejected)

-- prs=7, mhs 13
(2010, 29, '08:00', '09:40', 'Senin',   'GKB1-201', 'teori', 0),  -- kelas 201 (p1, full)
(2040, 30, '08:00', '09:40', 'Senin',   'GKB1-204', 'teori', 0),  -- kelas 204 (p2, full)
(2110, 31, '08:00', '09:40', 'Senin',   'GKB1-211', 'teori', 0),  -- kelas 211 (p3, approved)
(2120, 32, '10:00', '11:40', 'Kamis',   'GKB2-212', 'teori', 0),  -- kelas 212

-- prs=8, mhs 14
(2130, 33, '08:00', '09:40', 'Jumat',   'GKB3-213', 'teori', 0);  -- kelas 213 (kapasitas=0)