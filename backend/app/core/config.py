"""Application settings, loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# <repo root>/backend/app/core/config.py -> parents[3] == <repo root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Hybrid Quantum-Classical Energy TSP"
    app_env: str = "development"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- authentication -----------------------------------------------------
    # "supabase": the active mode. The browser signs in with Supabase Auth and
    # attaches the session's access token to every API call; this server
    # verifies that token's signature against the project's published JWKS
    # before any handler runs (see app/core/auth.py). The settings below are
    # used for exactly that.
    # "demo": no token is demanded and every request is admitted as a fixed
    # demo user. Useful for running the API with no Supabase project reachable;
    # it is not a security boundary, so never expose that mode beyond a demo
    # host.
    auth_mode: str = "supabase"

    # --- Supabase auth (auth_mode="supabase") -------------------------------
    # The API is a resource server for Supabase-issued user tokens. It needs the
    # project URL to know where to fetch the public signing keys (JWKS) and to
    # check the token's issuer; the audience is Supabase's default for a signed
    # in user. None of these are secrets: the URL is public, the JWKS is public,
    # and verification uses the project's PUBLIC keys. The service-role key is
    # never used to verify a user token.
    supabase_url: str = ""
    supabase_jwt_aud: str = "authenticated"
    # Only for projects that still sign with the legacy shared HS256 secret.
    # This project signs with ES256, so it is left empty and unused.
    supabase_jwt_secret: str = ""

    # Dataset location. The CSV is the source of truth for the network; the
    # exact filename is discovered by Phase 1's own loader, so the dataset is
    # never renamed or duplicated to suit the API.
    data_dir: str = "data"
    transmission_lines_csv: str = "transmission_lines.csv"

    # Where the route maps and the comparison figure are written. Same folder
    # the Phase 2 CLI uses, so both produce one set of images.
    outputs_dir: str = "outputs"

    # --- Assistant (RAG) ----------------------------------------------------
    # The grounded project assistant. Generation runs on a LOCAL model through
    # Ollama: no API key, no account, no per-token cost, and the GRIDOPT
    # dataset, solver results and documents never leave this machine.
    #
    # None of these are secrets - a host and a model name - so they are safe in
    # .env.example and safe to log.
    ollama_host: str = "http://127.0.0.1:11434"
    #: The local model that answers. Small on purpose: this runs on CPU here.
    #: Change it with ASSISTANT_MODEL, and `ollama pull` that model first.
    assistant_model: str = "llama3.2:3b"
    #: Cap on generated tokens (Ollama's num_predict). A grounded answer is a
    #: short paragraph; this is headroom, not a target.
    assistant_max_tokens: int = 800
    #: Context window handed to the model (num_ctx). This MUST comfortably
    #: exceed the grounding prompt plus the assembled context block, because
    #: Ollama truncates a longer prompt silently - see the note in llm.py.
    ollama_num_ctx: int = 8192
    #: Near-greedy. This is extraction from supplied context, not composition.
    ollama_temperature: float = 0.1
    #: How long Ollama keeps the model in memory after a request, so the next
    #: question does not pay the load cost again.
    ollama_keep_alive: str = "10m"
    #: Seconds to wait for a local answer. CPU inference is slow, and a first
    #: request also pays the model load, so this is generous by design.
    assistant_timeout_s: float = 180.0
    # Retrieval depth handed to the model. Small on purpose, for two reasons:
    # a tight context keeps the answer traceable to named sources, and every
    # extra chunk is prompt the local CPU model must process before it can
    # answer at all (see the measurements in assistant/context.py).
    assistant_top_k: int = 6
    # Where the built knowledge base is written. Rebuild it with
    #   python reindex_assistant.py
    assistant_index_file: str = "assistant_index.json"

    # Hybrid QAOA defaults, mirroring run_phase2.py exactly. A request may
    # override them; the execution mode is deliberately not one of the knobs -
    # the API always runs the local simulator.
    qaoa_window: int = 4
    qaoa_sweeps: int = 8
    qaoa_reps: int = 2
    qaoa_shots: int = 2048
    qaoa_maxiter: int = 20
    qaoa_restarts: int = 1
    qaoa_cvar: float = 0.25
    qaoa_seed: int = 7

    @property
    def data_path(self) -> Path:
        return PROJECT_ROOT / self.data_dir

    @property
    def transmission_lines_path(self) -> Path:
        """The conventional dataset filename, whether or not it is what is there.

        `app.dataio.network.dataset_info` reports the CSV actually loaded.
        """
        return self.data_path / self.transmission_lines_csv

    @property
    def outputs_path(self) -> Path:
        return PROJECT_ROOT / self.outputs_dir

    @property
    def assistant_index_path(self) -> Path:
        """The knowledge-base file the assistant retrieves from."""
        return self.outputs_path / self.assistant_index_file


@lru_cache
def get_settings() -> Settings:
    return Settings()
