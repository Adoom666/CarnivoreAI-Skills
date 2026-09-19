---
name: commit-message
description: writes a conventional commit message from the staged diff. use when the
  user says "write a commit message" or "/commit-msg".
---
# commit message
Read the staged diff with `git diff --cached`. Summarise it as one subject line under
72 characters in the imperative mood, then a blank line, then a short body explaining
why the change was made. Print it. Do not commit anything and do not run any other
command.
