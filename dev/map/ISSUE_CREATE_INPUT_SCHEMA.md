# Markdown Draft Input Schema

Canonical markdown draft format for workflow create commands that accept `--input`.

## Supported Commands

- `python3 dev/workflow create feature --input <draft_file>`
- `python3 dev/workflow create issue --input <draft_file>`

## Required Structure

The parser reads the first markdown heading as the title and the content after that heading as the description.

- Title:
  - required
  - first heading in the file
  - any heading level is allowed: `#`, `##`, `###`, and so on
- Description:
  - optional
  - all content after the first heading, up to the next heading or end of file
  - empty description is allowed

## Output Contract

The parser returns:

- `title`: non-empty string
- `description`: string, possibly empty

## Valid Example

```md
# Refactor materialize CLI

Make feature-level and issue-level materialization explicit in the CLI.
```

## Also Valid

```md
### Add issue creation from markdown draft

Support file-based title and description input for issue registration commands.
```

## Invalid Examples

Missing title heading:

```md
Plain text without any markdown heading.
```

Empty title heading:

```md
#    

Body text without a title.
```

## Error Scenarios

- No headings in file:
  - parser fails because title cannot be resolved
- Empty first heading:
  - parser fails because title is required
- File does not exist:
  - parser fails with file path in the error output
- File is unreadable:
  - parser fails with the OS error context

## Recovery Guidance

- If the parser reports missing headings, add a first heading such as `# My Title`.
- If the parser reports an empty title, put non-empty text after the first heading marker.
- If the parser reports file-not-found, confirm the draft path before rerunning the command.
- If the parser reports an empty description warning, either keep the title-only draft or add body text below the heading.

## Agent Workflow Notes

- Recommended temporary directory for generated drafts: `tmp/workflow/`
- Humans may still use inline `--title` and `--description` flags.
- `--input` must not be combined with `--title` or `--description` in the same command invocation.
