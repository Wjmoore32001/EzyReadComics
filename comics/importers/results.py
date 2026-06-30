from dataclasses import dataclass, field


@dataclass
class IssueListSaveResult:
    issues_seen: int = 0
    issues_created: int = 0
    issues_updated: int = 0
    issues_unchanged: int = 0
    issues_skipped: int = 0
    volumes_created: int = 0
    volumes_updated: int = 0

    associated_images_created: int = 0
    associated_images_deleted: int = 0
    associated_images_skipped: int = 0
    missing_remote_fields_skipped: int = 0

    field_update_counts: dict = field(default_factory=dict)

    def record_issue_fields(self, update_fields):
        for field_name in update_fields:
            self.field_update_counts[field_name] = (
                self.field_update_counts.get(field_name, 0) + 1
            )

    def record_relationship_result(self, relationship_result):
        self.associated_images_created += relationship_result.associated_images_created
        self.associated_images_deleted += relationship_result.associated_images_deleted
        self.associated_images_skipped += relationship_result.skipped_items
        self.missing_remote_fields_skipped += relationship_result.missing_remote_fields_skipped


@dataclass
class VolumeListSaveResult:
    volumes_seen: int = 0
    volumes_created: int = 0
    volumes_updated: int = 0
    volumes_unchanged: int = 0
    volumes_skipped: int = 0
    field_update_counts: dict = field(default_factory=dict)

    def record_volume_fields(self, update_fields):
        for field_name in update_fields:
            self.field_update_counts[field_name] = (
                self.field_update_counts.get(field_name, 0) + 1
            )


@dataclass
class VolumeBatchRefreshResult:
    volumes_matching_selection: int = 0
    volumes_selected_this_run: int = 0

    volume_batches_requested: int = 0
    api_requests_made: int = 0

    volumes_checked: int = 0
    volumes_returned_by_comicvine: int = 0
    volumes_updated: int = 0
    volumes_unchanged: int = 0
    volumes_not_returned_by_comicvine: int = 0
    unexpected_volumes_returned: int = 0

    field_update_counts: dict = field(default_factory=dict)

    def record_field_updates(self, update_fields):
        for field_name in update_fields:
            self.field_update_counts[field_name] = (
                self.field_update_counts.get(field_name, 0) + 1
            )


@dataclass
class CreditSyncResult:
    remote_items_seen: int = 0
    people_created: int = 0
    people_updated: int = 0
    roles_created: int = 0
    credits_created: int = 0
    credits_deleted: int = 0
    credits_kept: int = 0
    skipped_items: int = 0
    missing_remote_fields_skipped: int = 0


@dataclass
class RelationshipSyncResult:
    remote_items_seen: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    links_created: int = 0
    links_deleted: int = 0
    links_kept: int = 0
    associated_images_created: int = 0
    associated_images_deleted: int = 0
    skipped_items: int = 0
    missing_remote_fields_skipped: int = 0


@dataclass
class DateScanProgressResult:
    scan_kind: str = ""
    scan_date: object = None
    starting_offset: int = 0
    ending_offset: int = 0
    total_results: int = 0
    page_results: int = 0
    completed: bool = False