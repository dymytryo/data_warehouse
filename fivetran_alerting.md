Purpose

Because of Fivetran’s criticality to the operation of Divvy and BILL’s Spend & Expense platform, we need to be made aware of and have a record of failures and critical changes. This awareness must serve as an immediately actionable alert to the responsible engineering team, to minimize impact to the business and potentially our customers. This document details the planned alerting mechanism to be put in place.

Requirements





All alerts originating from Fivetran ingestion warnings and failures are made visible to the responsible data and engineering team.



This should include notifications of downtime, service changes or upgrades, or any other informational system notifications.



This should not include administrative messages originating from support or account executives.



An alert is visible within 5 minutes of the event occurring (inclusive of Fivetran’s own message latency).



Messages are made visible in a Slack channel that includes all relevant members of the responsible team (for example, service owners and on-call engineers).



Little to no custom code or infrastructure is necessary to transmit these alerts.

Current Process

Notifications for outages, failed connectors, etc. are all communicated via email. Each user can configure what types of notifications they want to receive, including subscribing to notifications for specific connectors. More details can be found in the Fivetran notifications documentation.

Proposed Process

Fivetran’s sole method of emitting messages is via email, which is documented in detail in the Fivetran notifications documentation. There are no other methods for relaying these alerts, and their own recommendation for transmitting notifications to other services is to bridge an email into the second system. The transmittal of notifications to Slack is documented in Fivetran’s Slack integration guidance.

Given that there are no other methods for collecting and alerting on Fivetran messages, we’ll implement the recommended Email-to-Slack pipeline.





These alerts will feed into a dedicated Slack channel (for example, #fivetran-alerts).



A primary responder (for example, a Fivetran admin) will be responsible for responding to all notifications through this channel.



If the primary responder is unavailable at the time of an alert that necessitates immediate attention, a designated backup responder will cooperate with the relevant team lead to resolve the issue.



Alerts to this channel will receive immediate attention, superseding any other ongoing work.*



Alerts that require any action require a ticket for tracking and pattern analysis.

Enhancements & Considerations

This system of relaying notifications from email to Slack does not provide a permanent record that can be queried or analyzed. As the Enterprise Data System Monitoring initiative matures, receiving alerts via email (as the sole method for Fivetran notifications) may be a capability built into this system, though it is not part of the MVP scope. This feature would be added in future iterations and will not be available within the current compliance review period.

Raising PagerDuty alerts for pipeline failures may become part of a wider-ranging, holistic data governance practice. This is a combination of capability and policy that is not in scope for this audit period or necessity at this time.

All notifications that are received in this channel should be considered actionable. A significant number of ignorable alerts (noise) will result in the channel being overlooked by service owners or on-call engineers. We should aim to reduce the noise that occurs on this channel by regularly reviewing notifications to determine if they can be filtered out.

*There is no P level (priority) assignment or triaging in place for data platform issues and bugs, which would ideally be replaced with more specificity in the future.
