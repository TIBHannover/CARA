"""Studies: creating them, listing them, and their settings."""

from dataclasses import asdict

from fastapi import APIRouter

from cara.api.auth import CurrentUserDep, StudyAdminDep, StudyRoleDep, SuperuserDep
from cara.api.deps import PipelineDep, StudiesDep, UsersDep
from cara.api.schemas import OverviewOut, StudyIn, StudyOut
from cara.db.models import Role, StudyRow
from cara.services.studies import StudyService, settings_of
from cara.settings import StudySettings

router = APIRouter(prefix="/studies", tags=["studies"])


def _out(study: StudyRow, role: Role, studies: StudyService) -> StudyOut:
    return StudyOut(
        id=study.id,
        name=study.name,
        role=role,
        locked=study.locked_at is not None,
        settings=settings_of(study),
        dataset=study.dataset.name,
        query_set=study.query_set,
        query_kind=studies.query_kind(study.id),
        cover_image_ids=studies.cover_images(study.id),
        overview=OverviewOut(**asdict(studies.overview(study.id))) if role == Role.ADMIN else None,
    )


@router.post("", status_code=201)
def create_study(body: StudyIn, _: SuperuserDep, pipeline: PipelineDep, studies: StudiesDep) -> StudyOut:
    """Create a study from the New study page: queries sampled, pools built and grouped, people added."""
    study = pipeline.new_study(
        body.name,
        body.dataset_id,
        body.query_set,
        body.encoder,
        body.k,
        body.queries,
        body.seed,
        body.unsure,
        body.annotators,
        body.admins,
    )
    return _out(study, Role.ADMIN, studies)


@router.get("")
def list_studies(user: CurrentUserDep, studies: StudiesDep, users: UsersDep) -> list[StudyOut]:
    """Return the studies the person may open, with their role in each."""
    return [_out(study, users.role_in(user, study.id), studies) for study in studies.list_for(user)]


@router.get("/{study_id}")
def get_study(study_id: int, role: StudyRoleDep, studies: StudiesDep) -> StudyOut:
    """Return one study."""
    return _out(studies.get(study_id), role, studies)


@router.put("/{study_id}/settings")
def update_settings(
    study_id: int, settings: StudySettings, role: StudyAdminDep, studies: StudiesDep
) -> StudyOut:
    """Store new settings; locked settings can't change once judging has started (409)."""
    return _out(studies.update_settings(study_id, settings), role, studies)
