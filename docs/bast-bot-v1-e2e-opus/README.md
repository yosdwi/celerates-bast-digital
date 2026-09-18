# BAST Bot V1 — End-to-End Opus Pack

Tujuan: implement langsung end-to-end di repo `celerates-bast-digital` menggunakan Claude Code Opus.

Tidak perlu implementasi bertahap manual. Opus harus:
1. baca codebase,
2. trace field/source aktual,
3. implement business rules,
4. extend CLI,
5. integrasi Hermes + WhatsApp group,
6. tambah Docker Compose status read-only,
7. reuse Prefect untuk automation jika dibutuhkan,
8. run test/lint/typecheck,
9. laporkan hasil dan gap.

Baca `OPUS_E2E_PROMPT.md` lalu jalankan dari root repo.
