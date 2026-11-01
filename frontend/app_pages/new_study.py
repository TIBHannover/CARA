"""New study (superusers): pick a dataset's query set, how candidates are sampled, and who judges."""

from collections import Counter

import streamlit as st

import styles
from client import ApiError, Dataset, QuerySet
from components import tours
from components.feedback import count
from components.pool_depths import depth_table
from state import client, remember

api = client()


def set_label(name: str, by_name: dict[str, QuerySet]) -> str:
    """Name a query set by the kind of its queries, and by its name too when another set has the same kind."""
    kind = by_name[name].kind
    shared = sum(s.kind == kind for s in by_name.values()) > 1
    return f"{name}: {kind} queries" if shared else f"{kind} queries ({by_name[name].queries})"


def add_dataset_help() -> None:
    """Explain how to add a dataset, which only the command line can do."""
    st.markdown(
        "Datasets are added on the command line: convert yours to CARA's folder layout (README, *Your own "
        "data*), put it under `data/`, then:"
    )
    st.code("cara dataset-add /data/my_dataset", language="bash")
    st.caption("With Docker, put `docker compose exec backend` before the command.")


def needed_encoding(dataset: Dataset) -> bool:
    """Return whether the dataset lacks the embeddings its query sets need."""
    unready = [s for s in dataset.sets if not (s.knn_encoders or s.given_encoders)]
    return bool(unready) or not dataset.encoders


def encoding_status(dataset: Dataset) -> None:
    """Show what each encoder has embedded, and the command for what is missing."""
    needed = needed_encoding(dataset)
    partial = [e for e, n in dataset.encoders.items() if n < dataset.images]
    text = any(s.kind != "image" for s in dataset.sets)
    if dataset.encoders:
        st.dataframe(
            [
                {
                    "encoder": e,
                    "images embedded": n,
                    "share": 100 * n / max(dataset.images, 1),
                }
                for e, n in sorted(dataset.encoders.items())
            ],
            hide_index=True,
            column_config={
                "images embedded": st.column_config.NumberColumn(format="localized"),
                "share": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
            },
        )
    st.dataframe(
        [
            {
                "query set": s.name,
                "queries": s.queries,
                "kind": s.kind,
                "ready with": ", ".join(sorted(set(s.knn_encoders) | set(s.given_encoders)))
                or "no encoder yet",
            }
            for s in dataset.sets
        ],
        hide_index=True,
    )
    if needed or partial:
        if needed:
            st.markdown(
                "**To sample nearest neighbours or group images**, embed the dataset, then Refresh. Without "
                "embeddings, a study judges every image on its own."
            )
            suggested = f"{'hf-dual' if text else 'hf-cls'}:<model id>"
        else:
            st.markdown("**Optional:** nearest neighbours search only embedded images. To search all:")
            suggested = partial[0]
        quoted = f'"{dataset.name}"' if " " in dataset.name else dataset.name
        st.code(f"cara encode {quoted} --encoder {suggested}", language="bash")
        st.caption(
            ":material/memory: Use a GPU: large encoders need one, and every encoder is much faster on one. "
            "Only what has no embedding yet is encoded, so the command can be run again."
            + (" Text queries need a text–image encoder (`hf-dual`)." if text else "")
        )
    if st.button("Refresh", icon=":material/refresh:", help="Read the embeddings again", type="tertiary"):
        st.rerun()


def row(key: str) -> list[st.delta_generator.DeltaGenerator]:
    """Return two columns with equally tall sections (`styles.new_study`); they stack on narrow screens."""
    with st.container(key=f"new-row-{key}"):
        return st.columns(2, gap="medium")


st.title("New study")
tours.show("new-study")
styles.new_study()
st.markdown(
    "A study: queries from a dataset, the pool of images each is judged against, and the people who judge "
    "them. Creating it builds and groups the pools; the guidelines come next."
)

created = st.session_state.pop("created_study", None)
if created is not None:
    st.success(
        f"Created **{created}**. Next, write the guidelines and choose the pilot queries.",
        icon=":material/check:",
    )
    st.page_link("app_pages/study.py", label="Open the study", icon=":material/arrow_forward:")
    st.stop()

datasets = sorted(api.datasets(), key=lambda d: d.name.lower())
if not datasets:
    st.info("No dataset yet.", icon=":material/dataset:")
    add_dataset_help()
    st.stop()

with styles.section("new-dataset", "1 · Dataset"):
    dataset = st.selectbox(
        "Dataset", datasets, format_func=lambda d: d.name, label_visibility="collapsed", width=420
    )
    if dataset.description:
        st.markdown(dataset.description)
    st.caption(
        f"{dataset.images:,} images · {count(len(dataset.sets), 'query set')} · "
        f"{count(dataset.studies, 'study')}"
    )
    with st.popover("Add a dataset", icon=":material/add:", type="tertiary"):
        add_dataset_help()

if not dataset.sets:
    st.warning(
        "No query sets: the dataset folder needs `queries/<set>.jsonl` (README, *Your own data*).",
        icon=":material/help:",
    )
    st.stop()

left, right = row("sampling")
with left, styles.section("new-queries", "2 · Queries"):
    by_name = {s.name: s for s in dataset.sets}
    set_name = st.selectbox(
        "Query set",
        list(by_name),
        format_func=lambda name: set_label(name, by_name),
        key=f"set-{dataset.id}",
    )
    query_set = by_name[set_name]
    queries = st.number_input(
        "Number of queries",
        1,
        query_set.queries,
        query_set.queries,
        help="A random sample of the set; all of them by default. Pilot queries are drawn from these later.",
    )

with right, styles.section("new-sampling", "3 · Candidate sampling"):
    st.caption("How each query's pool, the candidates annotators judge, is drawn from the collection.")
    # (name, caption) of each method this query set can use.
    methods: dict[str, tuple[str, str]] = {}
    if query_set.given_pools or query_set.given_encoders:
        methods["file"] = ("Given candidates", "Listed with each query, e.g. a pool from existing runs")
    if query_set.knn_encoders:
        methods["knn"] = ("Nearest neighbours", "Each encoder's images most similar to the query")
    methods["random"] = ("Random sample", "k images drawn at random: a baseline")
    pool = st.radio(
        "Method",
        list(methods),
        format_func=lambda source: methods[source][0],
        captions=[caption for _, caption in methods.values()],
        key=f"method-{dataset.id}-{set_name}",
    )
    k = None
    depths: dict[str, int] = {}
    if pool == "random":
        k = int(st.number_input("Images per pool (k)", 2, 5000, 50, step=10))
        st.caption("A baseline that no encoder shapes: few relevant images, unless relevance is common.")
    if pool == "knn":
        pooling = sorted(query_set.knn_encoders)
        depths = depth_table(f"depths-{dataset.id}-{set_name}", pooling, {pooling[0]: 50}, 50)
    if st.toggle("Show embeddings", needed_encoding(dataset), key=f"embeddings-{dataset.id}"):
        encoding_status(dataset)

left, right = row("people")
with left, styles.section("new-grouping", "4 · Grouping"):
    # Grouping needs embeddings of the pool's images, whichever method drew them.
    groupers: list[str | None]
    if pool == "file":
        groupers = [*sorted(query_set.given_encoders), *([None] if query_set.given_pools else [])]
    elif pool == "knn":
        groupers = [*sorted(query_set.knn_encoders)]
    else:
        groupers = [*sorted(dataset.encoders), None]
    encoder: str | None = st.selectbox(
        "Encoder",
        groupers,
        index=groupers.index(next(iter(depths))) if depths else 0,
        format_func=lambda name: name or "No encoder: judge one image at a time",
        key=f"enc-{dataset.id}-{set_name}-{pool}-{next(iter(depths), '')}",
        help="Groups every pool by visual similarity.",
    )
    if encoder is None:
        st.caption(
            "Every image is judged on its own, in pool order: no groups, Suggest mode or settings simulator."
        )
    else:
        st.caption(
            "Groups are ordered by similarity to the query."
            if encoder in query_set.knn_encoders
            else "These queries have no embedding of their own, so groups keep the candidates' order."
        )

with right, styles.section("new-labels", "5 · Labels"):
    st.markdown(
        ":green[:material/check:] **Relevant**: grade 1 in the qrels.\n\n"
        ":red[:material/close:] **Not Relevant**: grade 0.\n\n"
        ":orange[:material/help:] **Unsure**: for borderline images; left out of the qrels."
    )
    unsure = st.toggle("Offer Unsure", True, help="It can be switched off later, in the study's settings.")
    st.caption("Colours and short names can change later; label names and grades are fixed now.")

with styles.section("new-people", "6 · Name and team"):
    people = [u for u in api.usernames() if u != st.session_state.username]
    # A form: the name and people reach the server with the click, so Create works on the first click even
    # while the name field still has the focus.
    with st.form("new-study", border=False):
        name = st.text_input("Study name", f"{dataset.name} · {query_set.kind} → image", max_chars=256)
        annotators = st.multiselect(
            "Annotators",
            people,
            help="They judge the images. New accounts are made under a study's Study settings.",
        )
        adjudicators = st.multiselect(
            "Adjudicators",
            people,
            help="Optional: they set the final labels where annotators disagree or are unsure.",
        )
        admins = st.multiselect("Other admins", people, help="They manage the study with you.")
        submitted = st.form_submit_button("Create study", type="primary", icon=":material/add_circle:")
    if submitted:
        roles = Counter([*annotators, *adjudicators, *admins])
        twice = sorted(user for user, n in roles.items() if n > 1)
        if not name.strip():
            st.error("Give the study a name.")
        elif twice:
            st.error(f"Each person has one role in a study: {', '.join(twice)} has more than one.")
        elif pool == "knn" and not depths:
            st.error("Pick at least one pooling encoder in section 3.")
        else:
            body = {
                "name": name.strip(),
                "dataset_id": dataset.id,
                "query_set": set_name,
                "encoder": encoder,
                "pool": pool,
                "pool_depths": depths,
                "k": k,
                "queries": int(queries),
                "unsure": unsure,
                "annotators": annotators,
                "adjudicators": adjudicators,
                "admins": admins,
            }
            try:
                with st.spinner("Building and grouping the pools"):
                    study = api.create_study(body)
            except ApiError as error:
                st.error(str(error))
                st.stop()
            st.session_state.study_id, st.session_state.study_role = study.id, "admin"
            remember(cara_study=str(study.id))
            st.session_state.created_study = study.name
            st.rerun()
