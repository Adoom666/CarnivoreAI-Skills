"""The catalog index builder: read the repository, publish a signed index.

The job is four steps and each one is its own module, because each one has a
different failure posture:

- ``assemble``  reads the repository and REFUSES anything it cannot prove.
- ``review``    asks a model about each new version and records
                ``status: "unavailable"`` when it cannot get an answer.
- ``sign``      reads the one secret that matters and SKIPS loudly when it
                is absent.
- deployment    is shell in the workflow, because it is three AWS calls.

Nothing in here ever invents a value. A number the job could not measure is
an error or an explicit "unavailable", never a default.
"""
