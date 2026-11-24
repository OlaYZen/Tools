#!/usr/bin/env bash
# Remove the open-password from Norwegian payslip PDFs.
#
# Usage:
#   ./unlock-payslips.sh file1.pdf file2.pdf     # specific files
#   ./unlock-payslips.sh                          # every *.pdf in the current dir
#
# Each locked "name.pdf" becomes an unencrypted "name.unlocked.pdf" beside it;
# the original is left untouched. The password is typed once, hidden, and never
# stored in argv or shell history.

set -euo pipefail

# Pick a decryptor: qpdf is exact; pdftocairo (poppler) is the no-install fallback.
if command -v qpdf >/dev/null 2>&1; then
  engine=qpdf
elif command -v pdftocairo >/dev/null 2>&1; then
  engine=pdftocairo
else
  echo "Need qpdf (recommended: sudo apt install qpdf) or poppler's pdftocairo." >&2
  exit 1
fi

# Files: the arguments, or every PDF in the current directory.
if [[ $# -gt 0 ]]; then
  files=("$@")
else
  shopt -s nullglob
  files=(*.pdf)
fi
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No PDF files given or found." >&2
  exit 1
fi

# Prompt once, silently.
read -rs -p "PDF password (fødselsnummer): " pw
echo

fail=0
for f in "${files[@]}"; do
  [[ -f "$f" ]] || { echo "skip (not a file): $f" >&2; ((fail++)); continue; }
  out="${f%.pdf}.unlocked.pdf"
  if [[ "$engine" == qpdf ]]; then
    if qpdf --password="$pw" --decrypt -- "$f" "$out" 2>/dev/null; then
      echo "unlocked: $out"
    else
      echo "FAILED (wrong password?): $f" >&2; ((fail++))
    fi
  else
    if pdftocairo -pdf -upw "$pw" -- "$f" "$out" 2>/dev/null && [[ -s "$out" ]]; then
      echo "unlocked: $out"
    else
      echo "FAILED (wrong password?): $f" >&2; rm -f "$out"; ((fail++))
    fi
  fi
done

unset pw
[[ $fail -eq 0 ]] || { echo "$fail file(s) failed." >&2; exit 1; }
