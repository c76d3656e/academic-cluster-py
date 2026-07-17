"""Provider API exposes only capabilities consumed by the runtime."""

from academic_cluster.api.admin.providers import (
    ProviderCreateRequest,
    ProviderResponse,
    ProviderUpdateRequest,
)


def test_provider_api_does_not_advertise_unimplemented_routing_capabilities() -> None:
    unsupported = {"weight", "extra_keys", "extra_key_count", "key_strategy"}

    assert unsupported.isdisjoint(ProviderCreateRequest.model_fields)
    assert unsupported.isdisjoint(ProviderUpdateRequest.model_fields)
    assert unsupported.isdisjoint(ProviderResponse.model_fields)
