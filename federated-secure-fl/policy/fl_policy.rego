package fl

import rego.v1

default allow := false

allow if {
    input.role == "trainer"
    not revoked[input.client_id]
}

revoked contains id if {
    some id in data.revoked_clients
}
