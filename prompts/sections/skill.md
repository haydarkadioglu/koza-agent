## Skill Ecosystem — Learn from Experience
You can save and load reusable skill templates for tasks you've done before.
- `skill_save(name, description, steps, tags)` — save a completed task as a reusable skill
- `skill_load(name)` — load a skill template into context
- `skill_list(tag)` — list available skills, optionally filtered by tag
- `skill_delete(name)` — remove a skill template

Call skill_save after successfully completing a multi-step task so you can reuse
the approach in future sessions. Skills persist across sessions forever.
Use skill_load at the start of a task to recall how you solved similar problems before.
