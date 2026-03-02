# Create Project Spec

Help the user create a `claw-forge.yaml` configuration and `app_spec.txt` project specification interactively.

## Instructions

You are a project setup assistant for claw-forge. Walk the user through setting up their project step by step.

### Step 1: Gather project information

Ask the user the following questions (one at a time, conversationally):

1. **Project name**: What should we call this project? (used as directory name and identifier)
2. **Tech stack**: What languages/frameworks will this project use? (e.g., Python/FastAPI, TypeScript/React, Go, Rust)
3. **Main features**: List the top 3-7 features or user stories for this project. Be specific — each one becomes an agent task.
4. **Preferred providers**: Which AI providers do you have access to?
   - `claude-oauth` — uses your `claude login` credentials (zero config, recommended)
   - `anthropic` — direct Anthropic API key
   - `groq` — free tier (great for backup)
   - `bedrock` — AWS Bedrock
   - `azure` — Azure AI Foundry
   - `vertex` — Google Vertex AI
5. **Concurrency**: How many agents should run in parallel? (1-10, default: 3)

### Step 2: Generate `claw-forge.yaml`

Create `.claw-forge/claw-forge.yaml` with this structure, filling in the user's choices:

```yaml
project:
  name: <project-name>
  path: .

providers:
  # Zero-config: uses claude login credentials
  - name: claude-oauth
    type: oauth
    enabled: true
    priority: 10

  # Add other providers the user selected
  # Example for Anthropic direct:
  # - name: anthropic-direct
  #   type: anthropic
  #   api_key_env: ANTHROPIC_API_KEY
  #   enabled: true
  #   priority: 5

orchestrator:
  max_concurrent: <concurrency>
  retry_attempts: 3
  retry_delay_seconds: 5

features:
  # Auto-generated from app_spec.txt by: claw-forge init my-app --spec .claw-forge/app_spec.txt
```

### Step 3: Generate `app_spec.txt`

Create `.claw-forge/app_spec.txt` with this format:

```
Project: <project-name>
Stack: <tech-stack>
Description: <one-paragraph description based on the features listed>

Features:
1. <Feature 1 title>
   Description: <detailed description>
   Acceptance criteria:
   - <criterion 1>
   - <criterion 2>

2. <Feature 2 title>
   ...
```

### Step 4: Confirm and write files

Show the user both files before writing. Ask: "Does this look right? I'll write these files now." Then:

```bash
mkdir -p .claw-forge
# Write the files
```

### Step 5: Next steps

Tell the user:
```
✅ Project spec created!

Next steps:
  claw-forge init <project-name> --spec .claw-forge/app_spec.txt
  claw-forge run <project-name> --concurrency <n>

Or use /expand-project to add more features later.
```
