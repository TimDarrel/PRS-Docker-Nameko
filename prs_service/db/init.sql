-- ============================================================
-- PRS (Pembuatan Rencana Studi) Database Schema
-- ============================================================

CREATE DATABASE IF NOT EXISTS prs_db;
USE prs_db;

-- ----------------------------------------------------------
-- Table: PRS (header / rencana studi per mahasiswa)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS prs (
    id_prs          INT AUTO_INCREMENT PRIMARY KEY,
    id_mahasiswa    INT          NOT NULL,
    id_semester     INT          NOT NULL,
    dosen_wali_id   INT          NOT NULL,
    status          ENUM('draft', 'process', 'validated') NOT NULL DEFAULT 'draft',
    total_sks       INT          NOT NULL DEFAULT 0,       -- total SKS dari kelas yang di-approve
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_prs (id_mahasiswa, id_semester)
);

-- ----------------------------------------------------------
-- Table: PRS_Detail (kelas yang diambil dalam satu PRS)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS prs_detail (
    id_detail_prs   INT AUTO_INCREMENT PRIMARY KEY,
    id_prs          INT          NOT NULL,
    id_kelas        INT          NOT NULL,                 -- FK to Penawaran Kelas service
    id_mata_kuliah  INT          NOT NULL,
    prioritas       TINYINT      NOT NULL DEFAULT 1,       -- 1, 2, or 3
    sks             INT          NOT NULL,
    status_validasi ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_detail (id_prs, id_kelas),
    FOREIGN KEY (id_prs) REFERENCES prs(id_prs) ON DELETE CASCADE
);

-- ----------------------------------------------------------
-- Seed: sample PRS data
-- ----------------------------------------------------------
INSERT INTO prs (id_mahasiswa, id_semester, dosen_wali_id, status, total_sks) VALUES
(1, 1, 10, 'draft',     0),
(2, 1, 10, 'process',   9),
(3, 1, 11, 'validated', 18);

-- ----------------------------------------------------------
-- Seed: sample PRS_Detail data
-- ----------------------------------------------------------
INSERT INTO prs_detail (id_prs, id_kelas, id_mata_kuliah, prioritas, sks, status_validasi) VALUES
(2, 101, 1, 1, 3, 'pending'),
(2, 102, 2, 2, 3, 'pending'),
(2, 103, 3, 3, 3, 'pending'),
(3, 104, 4, 1, 3, 'approved'),
(3, 105, 5, 2, 3, 'approved'),
(3, 106, 6, 1, 3, 'approved'),
(3, 107, 7, 2, 3, 'approved'),
(3, 108, 8, 3, 3, 'approved'),
(3, 109, 1, 1, 3, 'rejected');