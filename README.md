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
4. commit the release file and open a pull request.

the pull request check refuses a diff that edits a skill folder without a
matching release, because the catalog would otherwise go on serving the
version you just edited away from.

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

## the review is advisory and it says so

every version gets one model's read of its own text, written at publish time
and shown in the app above the SKILL.md before anyone consents to install.

it is written after the publisher's signature has already been verified, so it
is covered by the index key alone. an index key holder could therefore forge a
benign review. that is why the review is never the thing that authorises an
install: the SKILL.md text is always shown next to it and the consent button
stays a human act.

when the review cannot be obtained, for any reason at all, the index records
`status: "unavailable"` and no summary. the app renders that literally as "no
ai review". a blank review must never read as a clean one.

## what signing buys, honestly

signing proves who wrote a skill. it does not prove a skill is safe. a
verified skill is a provenance claim: it makes an attacker attributable, it
does not make the bytes harmless. that is the whole reason the install preview
shows the text and the review, and why an update whose SKILL.md changed needs
fresh consent.

## still to do, and it is the owner's to do

branch protection on `main` is not set by this repository and cannot be. it
needs to require a pull request, require the `verify` job to pass, and include
administrators, or `CODEOWNERS` is a suggestion rather than a control.
