"""Launch the GeoFlow web server."""
import uvicorn


def main():
    print("\nGeoFlow starting at http://localhost:8000\n")
    uvicorn.run("geodb.web.app:app", host="0.0.0.0", port=8000, reload=False,
                h11_max_incomplete_event_size=10 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    main()
