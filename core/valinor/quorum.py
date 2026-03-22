"""
Quorum Voter — VAL-41: Replace pairwise reconciliation with N-agent quorum.

Instead of checking every pair of findings for >2x deviation (O(n^2)),
this module collects votes from multiple agents on each finding and
accepts/rejects based on configurable majority threshold.

Design:
  - Each agent can AGREE, DISAGREE, or ABSTAIN on a finding
  - A finding is accepted if voting agents pass the quorum threshold
  - Confidence is derived from agreement level (unanimity > bare majority)
  - Replaces the Haiku arbiter with a deterministic, cheaper mechanism

Architecture references:
  - Byzantine fault tolerance — quorum-based consensus
  - Ensemble learning — majority voting for classifier ensembles
  - Mixture of Agents (Wang et al., 2024) — multi-agent aggregation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


class Vote(str, Enum):
    """Agent vote on a finding."""
    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"


@dataclass
class AgentVote:
    """A single vote from an agent on a finding."""
    agent_name: str
    vote: Vote
    confidence: float = 0.5
    reason: str = ""


@dataclass
class FindingBallot:
    """Collected votes for a single finding."""
    finding_id: str
    finding: dict[str, Any]
    source_agent: str
    votes: list[AgentVote] = field(default_factory=list)

    @property
    def agree_count(self) -> int:
        return sum(1 for v in self.votes if v.vote == Vote.AGREE)

    @property
    def disagree_count(self) -> int:
        return sum(1 for v in self.votes if v.vote == Vote.DISAGREE)

    @property
    def abstain_count(self) -> int:
        return sum(1 for v in self.votes if v.vote == Vote.ABSTAIN)

    @property
    def voting_count(self) -> int:
        """Number of non-abstaining votes."""
        return self.agree_count + self.disagree_count

    @property
    def agreement_ratio(self) -> float:
        """Ratio of agree votes among voting (non-abstaining) agents."""
        if self.voting_count == 0:
            return 0.0
        return self.agree_count / self.voting_count


@dataclass
class QuorumResult:
    """Result of quorum voting on a finding."""
    finding_id: str
    accepted: bool
    agreement_ratio: float
    confidence: float
    total_votes: int
    agree_count: int
    disagree_count: int
    abstain_count: int
    dissenting_reasons: list[str] = field(default_factory=list)


@dataclass
class QuorumReport:
    """Complete quorum report for a set of findings."""
    results: list[QuorumResult] = field(default_factory=list)
    accepted_findings: list[dict[str, Any]] = field(default_factory=list)
    rejected_findings: list[dict[str, Any]] = field(default_factory=list)
    total_findings: int = 0
    acceptance_rate: float = 0.0

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Quorum: {len(self.accepted_findings)}/{self.total_findings} "
            f"findings accepted ({self.acceptance_rate:.0%} acceptance rate)."
        )


# ═══════════════════════════════════════════════════════════════════════════
# QUORUM VOTER
# ═══════════════════════════════════════════════════════════════════════════


class QuorumVoter:
    """
    Collects votes from multiple agents on findings and applies
    quorum-based acceptance/rejection.

    Usage:
        voter = QuorumVoter(threshold=0.5)
        voter.submit_finding("analyst", finding_dict)
        voter.cast_vote("FIN-001", "sentinel", Vote.AGREE, confidence=0.8)
        voter.cast_vote("FIN-001", "hunter", Vote.DISAGREE, reason="...")
        report = voter.tally()
    """

    def __init__(self, threshold: float = 0.5) -> None:
        """
        Args:
            threshold: Minimum agreement ratio to accept a finding (0.0–1.0).
                       Default 0.5 = simple majority.
        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"Threshold must be between 0.0 and 1.0, got {threshold}")
        self.threshold = threshold
        self._ballots: dict[str, FindingBallot] = {}

    def submit_finding(
        self,
        source_agent: str,
        finding: dict[str, Any],
    ) -> str:
        """
        Submit a finding for quorum voting.

        The source agent automatically gets an AGREE vote.

        Args:
            source_agent: Name of the agent that produced the finding.
            finding: The finding dict (must have an 'id' key).

        Returns:
            The finding_id used for subsequent votes.
        """
        finding_id = finding.get("id", f"finding_{len(self._ballots)}")

        ballot = FindingBallot(
            finding_id=finding_id,
            finding=finding,
            source_agent=source_agent,
        )
        # Source agent implicitly agrees with their own finding
        ballot.votes.append(AgentVote(
            agent_name=source_agent,
            vote=Vote.AGREE,
            confidence=float(finding.get("confidence", 0.8)),
            reason="Source agent (auto-agree)",
        ))

        self._ballots[finding_id] = ballot

        logger.debug(
            "finding_submitted_for_quorum",
            finding_id=finding_id,
            source_agent=source_agent,
        )

        return finding_id

    def cast_vote(
        self,
        finding_id: str,
        agent_name: str,
        vote: Vote,
        confidence: float = 0.5,
        reason: str = "",
    ) -> bool:
        """
        Cast a vote on a finding.

        Args:
            finding_id: ID of the finding to vote on.
            agent_name: Name of the voting agent.
            vote: AGREE, DISAGREE, or ABSTAIN.
            confidence: Agent's confidence in their vote (0.0–1.0).
            reason: Optional reason for the vote.

        Returns:
            True if vote was recorded, False if finding_id not found.
        """
        ballot = self._ballots.get(finding_id)
        if ballot is None:
            logger.warning("vote_for_unknown_finding", finding_id=finding_id)
            return False

        # Prevent duplicate votes from same agent
        existing = [v for v in ballot.votes if v.agent_name == agent_name]
        if existing:
            logger.warning(
                "duplicate_vote_ignored",
                finding_id=finding_id,
                agent_name=agent_name,
            )
            return False

        ballot.votes.append(AgentVote(
            agent_name=agent_name,
            vote=vote,
            confidence=confidence,
            reason=reason,
        ))

        logger.debug(
            "vote_cast",
            finding_id=finding_id,
            agent_name=agent_name,
            vote=vote.value,
        )

        return True

    def tally(self) -> QuorumReport:
        """
        Tally all votes and produce the quorum report.

        A finding is accepted if its agreement_ratio >= threshold.
        Confidence is derived from agreement level:
          - Unanimous agree: confidence = avg(agent confidences)
          - Bare majority: confidence = agreement_ratio * avg(agree confidences)

        Returns:
            QuorumReport with accepted/rejected findings.
        """
        report = QuorumReport(total_findings=len(self._ballots))
        results: list[QuorumResult] = []

        for finding_id, ballot in self._ballots.items():
            ratio = ballot.agreement_ratio

            # Compute confidence from voting agents
            agree_confs = [
                v.confidence for v in ballot.votes if v.vote == Vote.AGREE
            ]
            avg_agree_conf = (
                sum(agree_confs) / len(agree_confs) if agree_confs else 0.0
            )

            # Scale confidence by agreement level
            confidence = ratio * avg_agree_conf

            accepted = ratio >= self.threshold
            dissenting = [
                v.reason for v in ballot.votes
                if v.vote == Vote.DISAGREE and v.reason
            ]

            result = QuorumResult(
                finding_id=finding_id,
                accepted=accepted,
                agreement_ratio=ratio,
                confidence=confidence,
                total_votes=len(ballot.votes),
                agree_count=ballot.agree_count,
                disagree_count=ballot.disagree_count,
                abstain_count=ballot.abstain_count,
                dissenting_reasons=dissenting,
            )
            results.append(result)

            if accepted:
                report.accepted_findings.append(ballot.finding)
            else:
                report.rejected_findings.append(ballot.finding)

        report.results = results
        report.acceptance_rate = (
            len(report.accepted_findings) / max(report.total_findings, 1)
        )

        logger.info(
            "quorum_tally_complete",
            total=report.total_findings,
            accepted=len(report.accepted_findings),
            rejected=len(report.rejected_findings),
            threshold=self.threshold,
        )

        return report

    def reset(self) -> None:
        """Clear all ballots for a fresh voting round."""
        self._ballots.clear()


def reconcile_with_quorum(
    findings: dict[str, Any],
    threshold: float = 0.5,
) -> dict[str, Any]:
    """
    Drop-in replacement for reconcile_swarm that uses quorum voting.

    Takes the same input format (dict of agent_name -> agent_data) and
    returns the findings dict with _quorum_report attached.

    Args:
        findings: Dict of agent outputs from Stage 3.
        threshold: Quorum threshold (default 0.5 = majority).

    Returns:
        Updated findings dict with _quorum_report key.
    """
    import json
    import re

    voter = QuorumVoter(threshold=threshold)

    # Step 1: Submit all findings from all agents
    agent_findings: dict[str, list[dict]] = {}
    for agent_name, agent_data in findings.items():
        if not isinstance(agent_data, dict) or agent_data.get("error"):
            continue
        if agent_name.startswith("_"):
            continue

        parsed = _parse_findings(agent_data)
        agent_findings[agent_name] = parsed
        for f in parsed:
            voter.submit_finding(agent_name, f)

    # Step 2: Cross-vote — each agent votes on other agents' findings
    all_agents = list(agent_findings.keys())
    for finding_id, ballot in voter._ballots.items():
        source = ballot.source_agent
        finding = ballot.finding
        domain = finding.get("domain", "")
        value_eur = finding.get("value_eur")

        for other_agent in all_agents:
            if other_agent == source:
                continue

            # Check if this agent has a similar finding (same domain)
            other_findings = agent_findings.get(other_agent, [])
            matching = [
                f for f in other_findings
                if f.get("domain") == domain
                and f.get("value_eur") is not None
                and value_eur is not None
            ]

            if not matching:
                voter.cast_vote(
                    finding_id, other_agent, Vote.ABSTAIN,
                    reason="No comparable finding in this domain",
                )
                continue

            # If any matching finding has a similar value, agree
            if value_eur is not None:
                for mf in matching:
                    mv = float(mf.get("value_eur", 0))
                    fv = float(value_eur)
                    if fv > 0 and mv > 0:
                        ratio = max(mv, fv) / min(mv, fv)
                        if ratio < 2.0:
                            voter.cast_vote(
                                finding_id, other_agent, Vote.AGREE,
                                confidence=0.7,
                                reason=f"Similar value found (ratio {ratio:.1f}x)",
                            )
                        else:
                            voter.cast_vote(
                                finding_id, other_agent, Vote.DISAGREE,
                                confidence=0.6,
                                reason=f"Value mismatch (ratio {ratio:.1f}x)",
                            )
                        break
                else:
                    voter.cast_vote(
                        finding_id, other_agent, Vote.ABSTAIN,
                        reason="No numeric value to compare",
                    )

    # Step 3: Tally
    report = voter.tally()

    findings["_quorum_report"] = {
        "ran": True,
        "threshold": threshold,
        "total_findings": report.total_findings,
        "accepted": len(report.accepted_findings),
        "rejected": len(report.rejected_findings),
        "acceptance_rate": report.acceptance_rate,
        "summary": report.summary(),
        "results": [
            {
                "finding_id": r.finding_id,
                "accepted": r.accepted,
                "agreement_ratio": r.agreement_ratio,
                "confidence": r.confidence,
                "votes": f"{r.agree_count}A/{r.disagree_count}D/{r.abstain_count}X",
                "dissenting_reasons": r.dissenting_reasons,
            }
            for r in report.results
        ],
    }

    return findings


def _parse_findings(agent_data: dict) -> list[dict]:
    """Parse structured findings from agent output."""
    import json

    output = agent_data.get("output", "")
    if not output:
        return []

    try:
        start = output.find("[")
        end = output.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(output[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    return []
