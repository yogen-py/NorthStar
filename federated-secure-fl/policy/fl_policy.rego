package fl

import rego.v1

default allow := false

allow if {
    input.role == "trainer"
    not input.client_id in data.revoked_clients
}
