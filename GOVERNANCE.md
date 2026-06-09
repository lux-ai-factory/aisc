# Governance of the "AI Assessment Sandbox Configurator"

## Purpose

The "AI Assessment Sandbox Configurator" (called "The Project" in the rest of this document) is an open source initiative co-developed and co-maintained by the [Interdisciplinary Centre for Security, Reliability and Trust](https://www.uni.lu/snt-en/) at the University of Luxembourg (called "SnT" in the rest of this document) and by the [Luxembourg Institute of Science and Technology]([https://www.list.lu](https://www.list.lu)) (called "LIST" in the rest of this document). This initiative is funded under the [Luxembourg AI Factory]([https://aifactory.lu/](https://aifactory.lu/)) (Horizon Europe grant agreement n° 101234366).

This document defines the governance model of "The Project", including roles, responsibilities, and decision-making processes.

It aims to ensure transparent, consistent, and fair management of The Project.

It also clarifies how authority is delegated, how contributors may take on greater responsibility, and how project continuity is ensured over time.

## Scope

This governance document applies to the software codebase, documentation, issue tracking, release management, repository administration, public project communication, and related community processes of "The Project".

It covers the project's repositories, associated documentation, and official releases published under the "The Project" project.

This document does not replace or override applicable legal, contractual, institutional, or consortium obligations of the participating institutions.

## Governance Model

- "The Project" operates three tiers of participation:

| Tier                   | Who                                  | Authority                                                            |
| ---------------------- | ------------------------------------ | -------------------------------------------------------------------- |
| **Steering Committee** | 4 designated members (2 LIST, 2 SnT) | Strategic direction, roadmap, dispute resolution, governance changes |
| **Technical Leaders**  | 2 designated leaders (1 LIST, 1 SnT) | Day-to-day technical decisions, PR review and merge, releases        |
| **Contributors**       | Anyone                               | Code, documentation, tests, issues, discussion                       |

- The Steering Committee has the final authority over all aspects of the project, including technical and organizational decisions.
- The Steering Committee delegates authority to the Technical Leaders to ensure efficient day-to-day management while maintaining ultimate oversight.
- This model balances efficiency, accountability, and community input.
- Consensus is preferred, voting is not used as a governance mechanism for technical development.
- The decisions related to legal framework and Intellectual Property remain with the IP Steering Committee defined in the co-ownership agreement between SnT and LIST
- For the avoidance of doubt, this governance document governs project software development operations and decision-making, but does not transfer or redefine ownership of intellectual property, contractual rights, trademarks, or institutional legal responsibilities.

## Roles and Responsibilities

### Steering Committee

The Steering Committee:

- Provides overall vision and direction for The Project.
- Ensures alignment with The Project's mission and institutional context.
- Makes final decisions in case of disputes or lack of consensus.
- Delegates authority to Technical Leaders for routine technical and operational decisions.
- Appoints and removes Technical Leaders or Release Managers as needed.
- Represents the project in external matters (e.g., conferences, partnerships).
- The Steering Committee is expected to act in the best interest of the project, considering technical quality, sustainability, community input, and the institutional context of the consortium.
- Supporting coordination across consortium members where relevant.

Steering Committee decisions are made by consensus. In case consensus cannot be reached within one week, Steering Committee members should document the positions and do an open community consultation followed by a re-vote within two weeks. If a consensus still canot be reached, the status quo is preserved. The rationale for this mechanism is that the burden of proof rests with the party proposing change. Preserving the status quo when genuine disagreement exists protects the project and creates a natural incentive to build real consensus rather than win a vote.

The current Steering Committee members are:

- LIST: Jordi Cabot and Alessio Buscemi

- SnT: Maxime Cordy and Olivier Veneri

**Note:** Steering Committee membership will be revisited as the project grows and external stakeholders join. The Steering Committee may choose to expand beyond the founding institutions, provided institutional balance is preserved or a neutral foundation takes stewardship.

The Steering Committee meets at minimum once per quarter. Meeting notes are published to the Project repository within 14 days of each meeting.

### Technical Leaders

Technical Leaders are delegated by the Steering Committee to manage and supervise the technical and operational decisions for "The Project" with direct commit access to all repositories within "The Project". Technical Leaders:

- Review and merge pull requests.
- Ensure code quality, testing, and documentation standards.
- Participate in discussions and provide recommendations on technical matters.
- Mentor new Maintainers and new Contributors.

Technical Leaders are appointed by the Steering Committee. New Maintainers are appointed by the Technical Leaders after consultation with the Steering Committee, based on sustained quality contributions and community involvement.

Maintainers are expected to remain reasonably active. A Maintainer who is inactive for an extended period may be moved to emeritus or inactive status by the Technical Leaders.

Technical Leaders and Maintainers must follow the project's contribution, review, security, and release procedures.

The current Technical Leaders are Alessio Buscemi (LIST) and Olivier Veneri (SnT).

### Contributors

Contributors are anyone who participates in the project by:

- Reporting issues.
- Submitting pull requests.
- Contributing documentation or tests.
- Participating in discussions.

Contributors do not have decision-making authority by default, but their input is encouraged and considered as part of The Project's open development process.

All contributions are welcome and reviewed according to the CONTRIBUTING.md guidelines.

### Maintainers (optional)

Technical Leaders may delegate some of their tasks and commit rights to trusted Maintainers for specific repositories within "The Project". New Maintainers are appointed by the Technical Leaders after consultation with the Steering Committee, based on sustained quality contributions and community involvement.

Maintainers are expected to remain reasonably active. A Maintainer who is inactive for an extended period may be moved to emeritus or inactive status by the Technical Leaders. Maintainers must follow the project's contribution, review, security, and release procedures.

Maintainers act within delegated authority and do not independently define project strategy or override the Technical Leader's and the Steering Committee's final authority.

### Release Managers (optional)

Release Managers are individuals appointed by the Technical Leaders, after consultation with the Steering Committee, to coordinate and oversee project releases.

They:

- Prepare and maintain the release plan, release timeline, and release checklist.
- Coordinate feature freeze, testing, documentation readiness, and versioning for planned releases.
- Verify that release criteria have been met, including technical quality, packaging, and required documentation.
- Coordinate with Technical Leaders and Maintainers to resolve release-blocking issues.
- Publish or supervise the publication of official releases through approved project channels.
- Ensure that release notes accurately reflect major changes, known limitations, and migration considerations where applicable.
- Escalate unresolved release risks or disputes to the Technical Leaders.

Release Managers act within delegated authority and do not independently define project strategy or override the Technical Leader's or the Steering Committee's final authority.

## Delegation of Authority

To ensure efficient day-to-day project operation, the Steering Committee delegates routine technical and operational authority to Technical Leaders and, optionally when relevant, to Maintainers and Release Managers.

Technical Leaders may decide on routine matters, including pull request review, issue triage, minor refactoring, documentation improvements, testing practices, and ordinary repository maintenance.

Release Managers may coordinate release preparation, readiness checks, release scheduling, and publication activities for approved releases.

The following matters remain reserved to the Steering Committee unless explicitly delegated:

- Major changes in The Project's direction or scope
- Definition of roadmap, sustainability, and collaborations
- Adoption of significant architectural changes
- Appointment or removal of Technical Leaders, Maintainers and Release Managers
- Resolution of escalated disputes
- Exceptions to established project rules or governance
- Approval of governance amendments

## Decision-Making Process

- Consensus first: Decisions are made through open discussion in issues, pull requests, or meetings.
- Lazy consensus: If no objections are raised within 72 hours after a proposal is made, it is considered accepted.
- Escalation: If consensus cannot be reached, the Steering Committee makes the final decision after consulting the Technical Leaders and other relevant stakeholders.

Major decisions should, where reasonably possible, be documented transparently through repository discussions, meeting notes, architecture records, or other project records.

For substantial technical changes, Contributors are encouraged to open a Request for Comments (RFC) before implementation begins. Technical Leaders and Maintainers may require an RFC for changes they deem architecturally significant.

## Conflict Resolution

In case of conflicts between Contributors or Maintainers:

- Parties should first attempt to resolve the issue privately and respectfully.
- If unresolved, the matter may be brought before the Technical Leaders.
- The Steering Committee serves as the final arbiter if consensus cannot be achieved.
- All participants must abide by the project's Code of Conduct.

Where a conflict involves misconduct, harassment, or other Code of Conduct concerns, the matter may be handled under the project's Code of Conduct procedures rather than through ordinary technical governance channels.

Where a conflict involves legal, contractual, compliance, or intellectual property matters, the relevant institutional representatives of the consortium members remain responsible within their respective remit.

## Transparency and Communication

All governance and decision-making discussions occur publicly through:

- GitHub issues and pull requests
- Public mailing lists or chat channels
- Regular project meetings (if applicable)
- Meeting notes, major decisions, and policy updates are documented and shared openly in the project repository.

Confidential or restricted matters, including certain security, legal, personal, or contractual matters, may be handled in a limited-access setting where necessary.

## Amendments to Governance

Proposals to amend this governance document can be made by any Steering Committee member or by the Technical Leaders.

Amendments to this governance document require:

- A proposal submitted as a pull request with at least 30 days' public notice.
- Approval by the Steering Committee after consultation with the Technical Leaders.
- Publication of the updated document with version number and date.

Minor editorial corrections (typos, formatting, broken links) that do not materially change governance may be merged by the Technical Leaders without Steering Committee vote.

## License and Attribution

SnT and LIST jointly commit to release "The Project" under the Apache License, Version 2.0. All contributions are made under the same license unless explicitly stated otherwise.

All contributors are responsible for 3rd party licensing compliance on their respective contributions, making full licensing information available for Technical Leaders at any time.

Where required by project policy, external contributors may be required to sign the applicable Contributor License Agreement (CLA) before a contribution can be accepted as an authorized project contribution. The project may require either:

- an Individual Contributor License Agreement (ICLA), for contributors acting in their personal capacity, or
- a Corporate or Institutional Contributor License Agreement (CCLA), for contributions made on behalf of a company, university, research institute, or other legal entity.

The applicable CLA templates, contribution requirements, and related instructions are available in the project repository.

The collection, review, and record-keeping of signed CLAs are coordinated by the Technical Leaders, or by another function designated by the Steering Committee or the participating institutions.

By submitting a contribution, each Contributor is responsible for ensuring that they have the right to submit the contribution, including where such materials were generated, prepared, or modified with the assistance of automated or AI-based tools, and for complying with the applicable contribution, licensing, and attribution requirements set out by the project.

Project attribution, copyright notices, and contributor records shall be maintained in accordance with the project documentation and the applicable templates made available in the repository.

## Plug-in Catalogue of Tests and Controls

The plug-in catalogue operates in three tiers:

1. **Core plug-ins** live in the main repository and are governed under the governance described in this document. These are reference plug-ins that the project supports

2. **Verified plug-ins** live out-of-tree in their authors' own repositories and may carry a verification badge issued by The Project after passing a published checklist. The checklist, the issuance process, and the body responsible for awarding and revoking the badge will be defined by a subsequent RFC; until that RFC is accepted, the verified tier is not open.

3. **Community plug-ins** live out-of-tree and are listed in the public catalogue on a self-registration basis, with a clear unverified label. The registration mechanism will be defined by a subsequent RFC; until that RFC is accepted, the community tier is not open.

In the first release in May 2026, only the core tier is operational.

## Related Project Documents

This governance document should be read together with the following project documents, where applicable:

- README
- CONTRIBUTING.md
- CODE_OF_CONDUCT.md
- SECURITY.md
- LICENSE
- MAINTAINERS.md or equivalent maintainer list
- Release process or release checklist documentation

## Repository, Release, and Infrastructure Authority

Repository administration rights, release publication rights, package publication rights, and access to project infrastructure shall be limited to persons explicitly authorized by the Technical Leaders.

Administrative access should be granted only to the extent necessary and should be reviewed periodically.

Emergency actions, including security-related intervention or temporary access restrictions, may be taken by Technical Leaders or authorized Maintainers or Release Managers, but should be reported to the Steering Committee as soon as practicable.

Repositories: <https://github.com/lux-ai-factory/>

## Continuity and Succession

If a member of the Steering Committee becomes unavailable, resigns, or is no longer able to fulfil the role, an interim governance arrangement may be established jointly by the SnT and LIST until a successor is designated.

## Maintained by

For questions about this governance document, contact the Technical Leaders or the Steering Committee at: maxime.cordy@uni.lu
