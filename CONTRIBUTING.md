# Contributing to LensYou

Thanks for your interest in improving LensYou.

## Development setup
1. Fork and clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a local `.env` file (see README).
4. Run the app:
   ```bash
   python app.py
   ```

## Run tests
Use the existing test suite:
```bash
python -m unittest test_part_a_suite.py
```

## Pull request checklist
- Keep changes focused and minimal.
- Add/update documentation when behavior or UX changes.
- Run tests before opening a PR.
- Use clear commit messages.

## Issue labels used
- `bug`: Defect in existing behavior.
- `enhancement`: Feature or improvement request.
- `good first issue`: Beginner-friendly contribution.
- `help wanted`: Needs external contributor support.

## Code and review expectations
- Avoid unrelated refactors in the same PR.
- Keep security and privacy in mind for auth, admin, and payment flows.
- Include reproduction steps for fixes.
