from .contracts import SnapshotContext


class DataAccessViolation(ValueError):
    pass


class DataAccessPolicy:
    def check_context(self, context: SnapshotContext):
        if context.phase in ("F", "E") and context.capability in ("calibrate", "adapt"):
            raise DataAccessViolation("optimization forbidden in F/E")
        if context.phase == "E" and context.capability != "evaluate":
            raise DataAccessViolation("E phase is read-only evaluation")

    def select_forcing(self, context, rows):
        self.check_context(context)
        selected = []
        if context.forcing_mode == "R":
            # Prefer reanalysis; use issued forecasts only when a date has no reanalysis.
            by_date: dict = {}
            for row in rows:
                if row.valid_date not in context.dates:
                    continue
                if row.source_kind in ("reanalysis", "observation"):
                    existing = by_date.get(row.valid_date)
                    if existing is not None and existing.source_kind in ("reanalysis", "observation"):
                        raise DataAccessViolation("ambiguous duplicate forcing dates")
                    by_date[row.valid_date] = row
                elif (
                    row.source_kind == "forecast"
                    and row.available_at <= context.issue_time
                    and row.valid_date not in by_date
                ):
                    by_date[row.valid_date] = row
            selected = [by_date[d] for d in sorted(by_date)]
        else:
            for row in rows:
                if row.valid_date not in context.dates:
                    continue
                if row.available_at <= context.issue_time and (
                    row.source_kind == "forecast"
                    or context.end_of_day(row.valid_date) <= context.issue_time
                ):
                    selected.append(row)
            selected.sort(key=lambda row: row.valid_date)
            if len({r.valid_date for r in selected}) != len(selected):
                raise DataAccessViolation("ambiguous duplicate forcing dates")
        if not selected:
            raise DataAccessViolation("no legal forcing")
        return selected

    def select_flow(self, context, rows):
        self.check_context(context)
        # Only evaluation may receive future truth; forecasting never receives it in R either.
        selected = [
            r
            for r in rows
            if r.valid_date in context.dates
            and (
                (context.phase == "E" and context.capability == "evaluate")
                or (
                    r.available_at <= context.issue_time
                    and context.end_of_day(r.valid_date) <= context.issue_time
                )
            )
        ]
        if len({r.valid_date for r in selected}) != len(selected):
            raise DataAccessViolation("ambiguous duplicate flow dates")
        return sorted(selected, key=lambda r: r.valid_date)
