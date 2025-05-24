from dotenv import load_dotenv
from agents import Runner, Agent
from agents.mcp import MCPServerStdio
from agents.exceptions import AgentsException
import asyncio
from pydantic import BaseModel
from typing import List, Optional
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Schemas ===

class LocationItem(BaseModel):
    location_name: str
    latitude: float
    longitude: float
    rating: Optional[float] = None
    number_of_reviews: Optional[int] = None
    description: Optional[str] = None
    distance_meters: Optional[float] = None


class BusinessListOutput(BaseModel):
    businesses: List[LocationItem]


class SimilarAreaOutput(BaseModel):
    center_latitude: float
    center_longitude: float
    radius_meters: float
    matched_businesses: List[LocationItem]


class RunRequest(BaseModel):
    source_address: str
    source_radius: int
    destination_address: str
    destination_radius: int
    comparison_city: str
    industries: Optional[List[str]] = []


class RunResponse(BaseModel):
    source_businesses: BusinessListOutput
    destination_businesses: BusinessListOutput
    similar_area: SimilarAreaOutput


# === Helper function to run a business agent ===

async def run_business_agent(mcp_server: MCPServerStdio, address: str, radius: int, industries) -> List[LocationItem]:
    agent = Agent(
        name=f"Business Finder - {address}",
        handoff_description=f"Finds businesses near {address}",
        mcp_servers=[mcp_server],
        model="gpt-4.1-nano",
        instructions=(
            f"You are a Google Maps agent tasked with identifying businesses in {" or ".join(industries)} within a {radius}m "
            f"radius around {address}. For each business, return:\n"
            "- location_name (string)\n"
            "- latitude (float)\n"
            "- longitude (float)\n"
            "- rating (optional float)\n"
            "- number_of_reviews (optional int)\n"
            "- description (what the business does)\n"
            "- distance_meters (from starting point)\n"
            "Use only interactive, visible elements and report accurate results."
        ),
        output_type=BusinessListOutput,
    )

    prompt = (
        f"Identify and return a list of all the businesses in {" or ".join(industries)} in a {radius} meter radius near {address}."
    )

    result = await Runner.run(agent, prompt, max_turns=15)
    return result.final_output.businesses


# === API Endpoint ===

@app.post("/run", response_model=RunResponse)
async def run_agents(req: RunRequest):
    try:
        async with MCPServerStdio(
            name="Google Maps MCP",
            params={
                "command": "env",
                "args": [
                    f"GOOGLE_MAPS_API_KEY={os.getenv('GOOGLE_MAPS_API_KEY')}",
                    "npx",
                    "-y",
                    "@modelcontextprotocol/server-google-maps"
                ]
            }
        ) as googleMapsMcpServer:
            # Step 1: Run source business finder
            source_businesses = await run_business_agent(
                googleMapsMcpServer,
                req.source_address,
                req.source_radius,
                req.industries
            )

            # Step 2: Run destination business finder
            destination_businesses = await run_business_agent(
                googleMapsMcpServer,
                req.destination_address,
                req.destination_radius,
                req.industries
            )

            # Step 3: Run similarity agent using destination city
            similarity_agent = Agent(
                name="Similar Area Finder",
                handoff_description=f"Finds similar business clusters in {req.comparison_city}.",
                mcp_servers=[googleMapsMcpServer],
                model="gpt-4.1",
                instructions=(
                    f"You are a Google Maps agent tasked with finding a location in {req.comparison_city} "
                    f"that has a similar business composition regarding {" or ".join(req.industries)} to a provided "
                    f"list."
                    "Your output must include:\n"
                    "- center_latitude (float)\n"
                    "- center_longitude (float)\n"
                    "- radius_meters (float)\n"
                    "- matched_businesses (list of businesses matching the original cluster, each with location_name, "
                    "latitude, longitude, rating, number_of_reviews, description, distance_meters from center)"
                ),
                output_type=SimilarAreaOutput,
            )

            business_list_str = "\n".join(
                f"- {b.location_name} ({b.description}), rated {b.rating or 'N/A'} with {b.number_of_reviews or 0} reviews"
                for b in source_businesses
            )

            similarity_prompt = (
                f"Based on the following list of businesses:\n\n{business_list_str}\n\n"
                f"Find a similar area in {req.comparison_city} with a comparable mix of businesses in retail and production. "
                f"Return a center location (lat/lon), the search radius in meters, and a list of matching businesses."
            )

            similar_area_result = await Runner.run(similarity_agent, similarity_prompt, max_turns=20)

            return RunResponse(
                source_businesses=BusinessListOutput(businesses=source_businesses),
                destination_businesses=BusinessListOutput(businesses=destination_businesses),
                similar_area=similar_area_result.final_output
            )
    except AgentsException as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("maps_agent:app", host="localhost", port=443, reload=True)