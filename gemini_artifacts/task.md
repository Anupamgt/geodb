- [x] Create `pyproject.toml` in `/Users/rakeshkumar/Downloads/gdb`.
- [x] Install package and dependencies in editable mode via `pip3 install -e .`.
- [x] Extract codebase structure and document operations.
- [x] Compile findings into a `codebase_report.md` artifact.
- [x] Provide user with the final report.

## 3. Server Startup
- [x] Await successful completion of the `pip install -e .` background task.
- [x] Launch the `geodb-web` application (FastAPI server) locally on port `8000`.
- [x] Verify the server starts successfully and is accepting connections.
- [ ] Verify all command-line tools are available and display help menus.
  - [ ] `geodb --help`
  - [ ] `geodb-transform --help`
  - [ ] `geodb-agent --help`
  - [ ] `geodb-web --help`
- [ ] Verify basic execution (e.g. running `geodb stats`).
