from fastapi import APIRouter, Query

from app.models.schemas import LocationAutocompleteResponse, LocationSuggestion
from app.services.geocoding import autocomplete_locations

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("/autocomplete", response_model=LocationAutocompleteResponse)
async def autocomplete(
    query: str = Query(..., description="Partial city name or postal code"),
) -> LocationAutocompleteResponse:
    """Suggest cities or postal codes matching a partial query.

    Returns an empty list rather than an error for anything unresolvable —
    this backs live-typing autocomplete, where a dropdown just staying
    empty is the right behavior, not a surfaced failure.
    """
    suggestions = await autocomplete_locations(query)
    return LocationAutocompleteResponse(
        results=[
            LocationSuggestion(label=s.label, value=s.value) for s in suggestions
        ]
    )
