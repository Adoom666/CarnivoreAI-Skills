# carnivore skills catalog

this repository is the public place skills are published from. a build job
reads it, proves every release against this repository's own git history,
signs an index, and deploys that index to `https://catalog.carnivore.ai/v1/index.json`
with a detached signature beside it at `.../index.json.minisig`.

the app that reads it pins two public keys and refuses anything that does not
verify under them. so the honest summary of what this repository is: a place
where bytes get signed, and a job that refuses to sign anything it cannot
prove.

## what is here

| path | what it holds |
|---|---|
| `skills/<handle>/<name>/` | the skill itself, exactly as it gets installed |
| `releases/<handle>/<name>/<version>.json` | one signed release statement |
| `revocations/<handle>/*.json` | signed statements withdrawing a key or a version |
| `publishers/<handle>.json` | which keys a publisher signs with |
| `publishers/_index.json` | the public half of the index signing key |
| `catalog.yml` | the few settings that change what gets published |
| `digest_vectors.json` | shared with the app, so two digest implementations cannot drift |
| `tools/index_builder/` | the build job |
| `site/` | the header file and the one page the host serves |
| `.claude-plugin/marketplace.json` | generated; what `claude plugin marketplace add` reads |

## why the release statement lives outside the skill folder

the statement names the folder's digest. if it lived inside the folder it
would be part of what is being digested, and no digest could ever be right:
the file would change the number it is trying to state. so the skill folder
holds only what gets installed, and the statement sits beside it under
`releases/`.

each statement names a commit in this repository. the build job checks that
commit out, recomputes the digest with the same code the app uses, and
compares. so the index never points at bytes nobody signed, and the app can
download `codeload.github.com/Adoom666/CarnivoreAI-Skills/tar.gz/<commit>` and
arrive at the same number on its own.

## publishing a skill

1. put the folder at `skills/<your handle>/<name>/`. it needs a `SKILL.md`
   with a yaml front matter block carrying at least a `description`.
2. commit it. note the commit sha.
3. sign a release statement for that sha with the helper in the app's
   repository, `scripts/catalog-bootstrap/sign_release.py`. it computes the
   digest, renders the statement, signs it with your minisign key and writes
   `releases/<handle>/<name>/<version>.json`.
4. regenerate the plugin marketplace file, so the catalog and the file a
   Claude Code user installs from say the same thing:

   ```bash
   cd tools && python3 -m index_builder --repo-root .. marketplace --write
   ```

5. commit the release file and `.claude-plugin/marketplace.json`, then open a
   pull request.

the pull request check refuses a diff that edits a skill folder without a
matching release, because the catalog would otherwise go on serving the
version you just edited away from.

it also refuses a branch whose `.claude-plugin/marketplace.json` no longer
matches the releases, and prints the command above. the build job cannot write
that file itself: it holds a read only token, and a job that could push to
`main` would be a way around the review every other published byte goes
through. so the publisher regenerates it, and the check is what makes sure
they did.

## installing from here with the stock claude code cli

```
claude plugin marketplace add Adoom666/CarnivoreAI-Skills
claude plugin install sme@carnivore
```

`add` reads one file, `.claude-plugin/marketplace.json`, and each entry in it
points straight at a skill folder under `skills/`. a folder holding a
`SKILL.md` and no `skills/` subdirectory loads as a single skill, so no plugin
manifest is written into a skill folder and no copy of one is kept anywhere
else. that matters: a release statement names a folder's digest, so a file
added inside it would invalidate a signature, and a copy of it in a second
tree would be free to drift from the bytes that were signed.

this path is a convenience and it is NOT the signed one. **the cli copies the
skill folder as it stands on `main` at the moment you run it, not the commit a
publisher signed.** it does not check a release statement, and nothing here can
make it.

**the signature chain proves the catalog index, not the copy the cli made.**
minisign covers `v1/index.json` and the detached `.minisig` beside it; no
signature artifact is written into the plugin cache and nothing there is
verified afterwards. a user who wants the exact bytes a publisher signed
installs through the app instead, which checks the index against a pinned key
and then checks the folder digest before staging anything. the signature checking installer is the app's own
catalog screen, which verifies the index against a pinned key before it
stages anything. the same file is served at
`https://catalog.carnivore.ai/.claude-plugin/marketplace.json` for anyone who
wants to read what they are about to add.

## the build job

| job | what it holds | what it does |
|---|---|---|
| `inputs` | nothing | says which inputs are present, so a skipped pipeline is not silent |
| `verify` | nothing | proves every release, refuses an unreleased skill change, assembles an unsigned index |
| `review` | a model api key | writes one security review per new version |
| `sign` | the index signing key | signs the index and verifies its own signature |
| `deploy` | nothing secret | zips and ships to amplify, then checks the published headers |

`verify` runs on every pull request. the other three never do. secrets live in
aws secrets manager and are read through a role assumed with openid connect,
so no long lived aws credential is stored in github. every action is pinned to
a commit sha. the index is re-signed weekly even when nothing changed, which
bounds an undetected key compromise to a week rather than to forever.

## the review carries a verdict, and five kinds of finding block

every version gets one model's read of its own text. it answers two questions
in the same pass, because that is the ruling: does the frontmatter description
disclose what the body actually instructs, and does the body do anything on the
security checklist. it returns a `verdict` of `clean`, `flagged` or `blocked`.

five kinds of finding block a publish: `prompt_injection`, `credential_access`,
`obfuscation`, `opaque_payload` and `settings_write`. each is something no
legitimate skill in a public catalog needs to do, so a publish stops rather
than a reader being asked to notice a warning. the other six, `network`,
`shell_exec`, `file_delete`, `privilege`, `description_mismatch` and `other`,
are advisory: a skill that fetches documentation or runs a command is doing its
job, and the detail names the host or the path so a human can judge.

**the verdict is re-derived, never taken on trust.** the model is asked for it
so its answer is self consistent, and then the verdict is recomputed from the
findings and compared. a model that lists a blocking finding and calls itself
clean has its whole answer discarded, which records `unavailable`. the same
re-derivation runs on a committed review when it is read, so hand editing the
verdict in the file refuses the file rather than publishing it.

**the skill text is data, not instructions to the reviewer.** it is framed by
`=== BEGIN SKILL TEXT ===` and the prompt says so, because a skill IS
instructions to an agent: text addressed to the reviewer is the native attack
on this artifact class, and it is reported as `prompt_injection` rather than
followed.

**every utf-8 text member is shown, not three categories of file.** SKILL.md
first and executables next, so the size cap falls on the least important files
last. a file that is not text, and a file the cap left out, is named with its
size and marked as not shown, so a payload nobody can read is a thing the
reviewer can raise rather than a thing it never heard of.

it is written after the publisher's signature has already been verified, so it
is covered by the index key alone. an index key holder could therefore forge a
benign review. that is why the verdict gates the PUBLISH PIPELINE and is never
treated by the app as proof of anything: the SKILL.md text is always shown next
to it and the consent button stays a human act.

when the review cannot be obtained, for any reason at all, the index records
`status: "unavailable"` and no summary and NO VERDICT. the app renders that
literally as "no ai review". a blank review must never read as a clean one, and
an unavailable one is never a clean one.

## where a review lives, and when the model actually runs

a review is committed at `reviews/<handle>/<name>/<version>.json`, mirroring the
release tree one level out, so the signed statement for a version and the review
of the same bytes sit at the same coordinates. the file holds exactly the
`review` block the index carries, plus the `digest` it was taken over.

**a review is bound to a digest, not to a version number.** the build refuses to
reuse a committed review whose recorded digest is not the digest of the version
it is building, because a review of different bytes is not a review of these
bytes. a malformed artifact is treated as absent rather than as a review, and
the job log names the file and the reason.

the build fills in each version's review from the first of these that answers:

1. a committed review under `reviews/` for that version, at a matching digest.
2. a review this catalog already published for the same digest.
3. a model call.

**nothing becomes unreviewed.** the third rung is unchanged: a version with
neither a committed nor a published review is reviewed at build time exactly as
it always was. the first two rungs stop the catalog paying twice for the same
bytes; they do not stop anything being reviewed. the review step writes a table
into the job summary saying which rung answered for every version, so a reader
can see whether a model ran at all.

approval is what will write these files. the ruling of 2026-09-16 is that a
submitted skill sits in a bucket until it is approved, and the approval runs the
scan once against the bytes it is about to publish and commits the result beside
the release. that endpoint is not built yet. the same operation runs by hand:

```bash
cd tools && python3 -m index_builder --repo-root .. \
  review --handle <handle> --name <name> --version <version>
```

it verifies the release statement first and binds the review to the digest that
verification produced, so a review can never be committed for bytes nobody
signed. it reads the model key from `OPENROUTER_SECRET_VALUE`, and it writes
nothing at all when the scan fails: an unavailable review is a transient
failure, not a verdict, and committing one would leave a file a reader could
mistake for a finding.

**the approval moment is before any commit**, so the same command takes
`--staged <folder>` and reviews a skill folder on disk, computing the digest
from those bytes with the code the app uses. that is what
`scripts/catalog-bootstrap/fetch_approved.py` in the app's repository runs
after it stages an approved submission, and it prints the publish command only
when this exits zero.

**a blocked verdict exits non zero.** to publish one anyway, run it again with
`--override-blocked "<reason>"`. the reason, who you are and the moment are
written into the committed review as an `override` block. it NEVER changes the
verdict: the artifact still says blocked, the card still marks the item, and
the file sits under `reviews/`, which `CODEOWNERS` routes to the owner, so the
override shows up in the pull request diff rather than being applied silently.
`--require-clean` refuses anything that is not clean, not only what is blocked.

**the backstop runs in `verify`, which every pull request reaches.**
`check-reviews` reads the committed reviews for the versions just assembled and
refuses the build when one is blocked with no well formed override, or when one
exists and cannot be read. a gate that only lives in the script a maintainer
runs is a gate a hand commit walks past.

**a review with no verdict is stale.** everything reviewed before the verdict
existed answered a question the gate does not ask, so neither the committed
tree nor the live index carries one forward: those versions are reviewed once
more under the current prompt.

## the grade is advisory too

every version also carries a quality grade of its own text and structure,
written at publish time beside the review and shown in the verify job's
summary. it asks a different question from the review: not whether a skill
does anything damaging, but whether it is built the way the agent skills
specification says to build one, so an agent can find it, load it and follow
it.

**a low grade never blocks a publish.** what a publisher ships is the
publisher's business. nothing in the build refuses a version for its grade,
and nothing ever should.

every rule the grader applies cites the published requirement or
recommendation it came from, by url, in the table at the top of
`tools/index_builder/grade.py`. a rule that cannot be traced to one does not
exist, and a test fails the build if one appears. where the specification
asks for a judgement a machine cannot make, the grader either uses a stated
proxy and says in the note that it is one, or it declines and records the
rule as not graded. a rule that did not run is never reported as one that
passed, for the same reason a blank review must never read as a clean one.

a folder with no readable `SKILL.md` grades as `ungraded` rather than as an
`f`. an `f` is a measurement; that is the absence of one.

## what signing buys, honestly

signing proves who wrote a skill. it does not prove a skill is safe. a
verified skill is a provenance claim: it makes an attacker attributable, it
does not make the bytes harmless. that is the whole reason the install preview
shows the text and the review, and why an update whose SKILL.md changed needs
fresh consent.

## branch protection on `main`

`main` requires a pull request, and requires the `verify and assemble` check to
pass before a merge. force pushes and branch deletion are refused. code owner
review is required, so `CODEOWNERS` is a control rather than a suggestion for
anybody who is not the owner.

**administrators are deliberately NOT included.** including them is the
textbook answer and it is the wrong one here: this is a one person repository,
so an owner who cannot approve his own pull request and cannot bypass the check
has no way to land an urgent fix to his own catalog, and the failure mode of
that is a catalog that cannot be repaired. the owner keeps a way through. every
other contributor is held to the full set.

what that trades away, said plainly: the protection stops a mistake and stops a
contributor, and it does not stop a compromise of the owner's own account.
nothing set at this layer could.

## what a generated file is allowed to carry

`.claude-plugin/marketplace.json` is generated, and every description in it is
copied verbatim from a publisher's own `SKILL.md`, inside a folder whose digest
that publisher signed. so **this repository's no dash rule does not reach it.**
that rule governs prose we write. normalising a character in generated output
would be rewriting somebody else's signed words, and the same reasoning would
then demand stripping the emoji, arrows and box drawing that four of the six
published skills carry in their own descriptions.

control characters are the one exception, and they are a different case: a C0
control is not a word, it is an instruction to whatever renders the file.
`frontmatter.brief_of` strips every one of them, and a test asserts the shipped
file carries none.
