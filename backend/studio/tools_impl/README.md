# `backend/studio/tools_impl/` — what the agent can actually do

One module per tool the Studio agent may call. These are the **effects**: a shell, a file
write, a recursive delete, an environment change.

## The sentence on four of these files, and why it is there

> *admission makes a caller admitted, not an owner.*

A shell here can restart units, edit files and read any secret this process holds. A write
can replace the source a release is built from. A recursive delete is the least recoverable
effect on this surface. Setting an environment variable can flip a surface switch for the
whole process.

Being able to reach the surface is not the same as being entitled to those, and the
distinction has to live in the tool rather than in front of it — there is no gate in front
of it and there will not be one.

Every tool here bounds what it can touch and says so in its own header. Read the header
before adding a capability, and add the bound in the same commit as the capability.
