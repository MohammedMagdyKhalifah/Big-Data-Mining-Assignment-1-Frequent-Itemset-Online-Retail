# Submission Checklist (verified against the assignment PDF)

## Assignment requirements

- [x] Mini Project Description: objective, problem, dataset, suitability (report §1)
- [x] Item defined / Basket defined (report §1.5)
- [x] At least 3 Chapter 6 concepts; 8 are covered (report §4)
- [x] Textual, mathematical and algorithmic explanation for each (report §4, §5.4 pseudocode)
- [x] Data preprocessing with before/removed/after table (report §3, Table 1)
- [x] Candidate generation, itemset counting, minimum-support selection (report §5.4–5.5)
- [x] Frequent itemsets and association rules, confidence thresholds (report §5.6, §8.3)
- [x] Hashing/sampling/distributed processing addressed: not used, explained why (report §5.7)
- [x] Concepts demonstrated visibly: concept → implementation → evidence table (report §7)
- [x] Tables (1–7) and figures (1–6) with captions
- [x] Support experiment, confidence experiment, pruning experiment, scalability experiment, execution time
- [x] Interpretation: *why* results change (report §9)
- [x] Complete commented code + code appendix (Appendix A)
- [x] References in IEEE style + `references/references.bib`
- [x] English Markdown report + Arabic explanation
- [x] README, requirements.txt, tests (18 passing)

## Manual steps before submitting

- [ ] Replace `[STUDENT_NAME]` and `[STUDENT_ID]` at the top of the report.
- [ ] Rename `XXXXXXXX_FirstNameLastName_5113_Assignment_1.md` to your ID and name (e.g. `481013386_MohammedKhalifah_5113_Assignment_1`).
- [ ] Open the Markdown in Word (or convert with Pandoc: `pandoc report.md -o report.docx --resource-path=report`). Check that equations and figures came through, then save as .docx/.pdf with the same base name.
- [ ] Add your name and ID as a page header on every page in Word.
- [ ] Zip the folder as `XXXXXXXX_FirstNameLastName_5113_Assignment_1.zip`. Exclude `.venv/`, `.idea/`, `data/raw/*.xlsx`, `data/raw/*.zip` and `data/processed/*.pkl`, because they are large and reproducible (the README explains how to download the data).
- [ ] Do not submit `شرح_الواجب_والحل.md` or this checklist (they are for you only).
