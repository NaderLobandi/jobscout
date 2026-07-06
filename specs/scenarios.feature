Feature: Job matching with user preferences

Scenario: Internship-only profile filters out full-time roles
  Given a profile with employment_types [internship]
  When a full-time job is retrieved from any source
  Then the job is excluded before scoring

Scenario: Dealbreaker filtering is deterministic
  Given a profile with dealbreaker "on-call rotation"
  When a job description contains "on-call rotation"
  Then the job is excluded before any LLM call

Scenario: High match produces a draft package
  Given a job scoring above the threshold
  When the orchestrator completes the scoring phase
  Then a tailored cover letter draft is generated
  And the package is presented at the HITL gate
  And no application is submitted automatically

Scenario: PII never reaches the model
  Given a resume containing the user's email and phone
  When any agent sends resume content to the LLM
  Then the content contains placeholders instead of real PII

Scenario: Duplicate jobs across sources are merged
  Given the same job appears on RemoteOK and The Muse
  When search results are normalized
  Then only one Job record is returned

Scenario: Rerun skips seen jobs
  Given a job was presented in a previous session
  When the orchestrator runs again
  Then that job is not re-scored or re-presented
