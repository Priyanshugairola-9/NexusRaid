"""Financial transactions: amounts, frequency, accounts, merchants and channels."""

import numpy as np

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput, Role
from app.analyzers.checks import distribution_table, event_bursts, percentile_metrics

ENTITY_KINDS = ("categorical", "identifier")


class FinancialAnalyzer(BaseAnalyzer):
    domain = "financial"
    title = "Financial transactions"
    description = "Individual payments or transactions with amounts and parties."
    risk_supported = False
    risk_unsupported_reason = ("Statistical outliers in transactions are not evidence of fraud, and no labelled, "
                               "validated fraud model is available, so no risk level is assigned.")
    roles = (
        Role("amount", "Amount", ("amount", "amt", "price", "payment*", "debit", "credit", "transaction amount")),
        Role("transaction", "Transaction", ("transaction*", "txn*", "tx", "trans"), kinds=ENTITY_KINDS),
        Role("account", "Account", ("account*", "acct", "customer*", "card*", "payer", "client"), kinds=ENTITY_KINDS),
        Role("merchant", "Merchant", ("merchant*", "vendor*", "payee", "store", "shop"), kinds=("categorical",)),
        Role("category", "Category", ("category", "mcc", "type"), kinds=("categorical",), core=False),
        Role("balance", "Balance", ("balance",), core=False),
        Role("currency", "Currency", ("currency", "ccy"), kinds=("categorical",), core=False),
        Role("channel", "Channel", ("channel", "method", "mode"), kinds=("categorical",), core=False),
    )

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        amount = ctx.first("amount")
        if amount:
            percentile_metrics(ctx, out, amount, "Amount")
            values = ctx.numeric(amount)
            out.metrics.append({"label": "Negative amounts (refunds/reversals?)",
                                "value": int(np.sum(values < 0)), "column": amount})
            out.metrics.append({"label": "Statistically unusual amounts",
                                "value": ctx.anomalies.summary.get("column_flag_counts", {}).get(amount, 0),
                                "column": amount})
        account = ctx.first("account")
        if account and ctx.column_profile(account)["kind"] == "categorical":
            event_bursts(ctx, out, account, "1h", "account", "transactions")
        elif account:
            out.skipped("Bursts per account", f"{account} is unique per row, so it cannot group transactions.")
        else:
            out.skipped("Bursts per account", "No account column found.")
        for role, title in (("merchant", "Merchants / categories"), ("category", "Categories"),
                            ("channel", "Channels"), ("currency", "Currencies")):
            column = ctx.first(role)
            if column:
                distribution_table(ctx, out, column, title)
        if ctx.time_column:
            hours = ctx.frame[ctx.time_column].dt.hour.value_counts().sort_index()
            out.tables.append({"title": "Transactions by hour of day", "columns": ["hour", "transactions"],
                               "rows": [[int(hour), int(count)] for hour, count in hours.items()]})
        out.notes.append("NexusRaid never labels a transaction as fraud. Unusual amounts or bursts are leads "
                         "for review by someone who knows the accounts.")
        return out
