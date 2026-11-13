"""Student performance: score distributions, subject relationships, unusual records."""

import numpy as np

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput, Role
from app.analyzers.checks import bounds_check
from app.services.explanation import make_finding
from app.utils.data_utils import format_number, round_or_none

SUBJECT_WORDS = ("math*", "science", "physics", "chemistry", "biology", "english", "history", "geography",
                 "hindi", "computer", "economics", "accounts", "sanskrit", "social")


class StudentAnalyzer(BaseAnalyzer):
    domain = "student"
    title = "Student performance"
    description = "Marks, attendance and related records of students."
    risk_supported = False
    risk_unsupported_reason = ("Predicting an individual student's future would need validated models and "
                               "ethical safeguards; NexusRaid only describes patterns in the data.")
    roles = (
        Role("student", "Student", ("student*", "roll", "pupil*", "learner*", "enrol*", "enroll*", "admission"),
             kinds=("identifier", "categorical")),
        Role("score", "Score", ("score*", "marks", "mark", "grade*", "gpa", "cgpa", "sgpa", "exam*", "test*",
                                "quiz*", "percentage") + SUBJECT_WORDS),
        Role("attendance", "Attendance", ("attendance", "present*", "absent*", "absences")),
        Role("study", "Study time", ("study*", "homework"), core=False),
        Role("subject", "Subject / class", ("subject*", "course*", "class", "section", "semester"),
             kinds=("categorical",), core=False),
    )

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        scores = ctx.roles.get("score", [])
        rows = []
        for column in scores:
            values = ctx.numeric(column)
            finite = values[np.isfinite(values)]
            if finite.size and np.mean((finite >= 0) & (finite <= 100)) >= 0.95:
                bounds_check(ctx, out, column, 0, 100, "score out of 100")
            rows.append([column, round_or_none(np.mean(finite), 1), round_or_none(np.median(finite), 1),
                         round_or_none(np.std(finite), 1), round_or_none(finite.min(), 1),
                         round_or_none(finite.max(), 1)])
        if rows:
            out.tables.append({"title": "Score columns", "columns": ["column", "mean", "median", "std", "min", "max"],
                               "rows": rows})
        for column in ctx.roles.get("attendance", []):
            bounds_check(ctx, out, column, 0, 100, "attendance percentage")
        self._relationships(ctx, out, scores)
        if len(scores) >= 3:
            self._inconsistent_rows(ctx, out, scores)
        else:
            out.skipped("Unusual subject combinations", "Needs at least three score columns.")
        for column in ctx.profile["columns"]:
            if "label_candidate" in column["roles"] and column.get("top_values"):
                out.tables.append({"title": f"Outcome column '{column['name']}' (not used as an input)",
                                   "columns": ["value", "rows", "%"],
                                   "rows": [[item["value"], item["count"], item["pct"]] for item in column["top_values"]]})
        out.notes.append("Patterns describe groups in this dataset. They are not predictions about any "
                         "individual student.")
        return out

    def _relationships(self, ctx, out, scores) -> None:
        correlations = ctx.profile.get("correlations", {})
        if not correlations.get("available"):
            out.skipped("Relationships between columns", "Not enough numeric columns.")
            return
        names = correlations["columns"]
        drivers = ctx.roles.get("attendance", []) + ctx.roles.get("study", [])
        pairs = []
        for driver in drivers:
            for score in scores:
                if driver in names and score in names:
                    rho = correlations["matrix"][names.index(driver)][names.index(score)]
                    if rho is not None and abs(rho) >= 0.4:
                        pairs.append((driver, score, rho))
        out.ran("Relationships between columns", "Spearman correlation, |rho| >= 0.4 reported")
        if pairs:
            out.findings.append(make_finding(
                source=self.domain, category="relationship", severity="info",
                title=f"{len(pairs)} moderate-to-strong relationship(s) between attendance/study time and scores",
                what_happened="; ".join(f"{a} and {b}: rho {rho:.2f}" for a, b, rho in pairs[:6]) + ".",
                columns=sorted({name for pair in pairs for name in pair[:2]}),
                observed=f"{len(pairs)} pair(s) with |rho| >= 0.4.",
                comparison="0 = no relationship; 1 = always rise together; -1 = one rises as the other falls.",
                why_flagged="Relationships between effort measures and results are useful context.",
                method="Spearman rank correlation",
                could_indicate="Students who attend or study more tend to score higher here. This is an "
                               "association in this group, not proof that one causes the other.",
                confidence="medium", confidence_basis="Correlation in one dataset; other factors are not controlled.",
                needs="Background information (prior marks, course differences) to compare fairly.",
                next_steps="Use this as context, not as a judgement about individuals.",
            ))

    def _inconsistent_rows(self, ctx, out, scores) -> None:
        data = ctx.frame[scores].astype(float)
        deviations = data.sub(data.mean(axis=1), axis=0)
        values = deviations.to_numpy().ravel()
        values = values[np.isfinite(values)]
        median = np.median(values)
        scale = 1.4826 * np.median(np.abs(values - median))
        out.ran("Unusual subject combinations", "a subject far from the student's own average")
        if scale == 0:
            return
        extreme = (deviations.abs() / scale) > 4
        rows = np.flatnonzero(extreme.any(axis=1).to_numpy())
        if rows.size == 0:
            return
        example = rows[0]
        column = deviations.iloc[example].abs().idxmax()
        out.findings.append(make_finding(
            source=self.domain, category="anomaly", severity="notice",
            title=f"{rows.size} record(s) where one subject is far from that student's other subjects",
            what_happened="In these rows, one score differs strongly from the same student's average.",
            columns=scores,
            observed=f"Example: data row {example + 1}, {column} = {format_number(data.iloc[example][column])} "
                     f"versus a personal average of {format_number(data.iloc[example].mean())}.",
            comparison=f"Typical gap between a subject and the student's own average: about {format_number(scale)} "
                       "points; flagged above 4x that.",
            why_flagged="Large internal inconsistencies are often data-entry errors (e.g. a typo or a mark entered "
                        "in the wrong column).",
            method="Within-row deviation from the row mean",
            could_indicate="A data-entry error, an absent or special exam, or a genuine difference.",
            confidence="medium", confidence_basis="Relative to the spread of such gaps in this dataset.",
            needs="The original mark sheets for these rows.",
            next_steps="Check these rows against the source records.",
            evidence={"rows": [int(row) + 1 for row in rows[:50]]},
        ))
