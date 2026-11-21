"""Shared category boundaries for extraction and evidence verification (CUAD 41)."""

CATEGORY_CRITERIA = {'Document Name': "Identify the document's actual title; do not infer it from its filename.",
 'Parties': 'Identify all named contracting parties and roles. Do not fill placeholders or treat '
            'mentioned third parties as signatories.',
 'Agreement Date': 'Check the stated signing/agreement date. A filing date, filename or [Date] '
                   'placeholder is not an actual agreement date.',
 'Effective Date': 'Check effectiveness conditions and dates together. Do not infer execution, '
                   'signatures or seals that are not evidenced.',
 'Expiration Date': 'Distinguish initial duration from an exact expiration date. A calculated date '
                    'requires every premise and explicit calculation.',
 'Renewal Term': 'Check renewal duration, frequency, conditions and exceptions. Do not infer '
                 'indefinite repeated renewals or unilateral rights.',
 'Notice Period To Terminate Renewal': 'Only nonrenewal/termination-of-renewal notice qualifies. '
                                       'Postal delivery, payment and cure periods are different. '
                                       'Preserve units and conditions.',
 'Governing Law': 'Look for the law governing the contract, not arbitration venue, courts, '
                  'incorporation jurisdiction or a heading alone.',
 'Insurance': 'Check an obligation to maintain or obtain insurance and its scope; mere mention of '
              'an insurer is insufficient.',
 'Audit Rights': "Check a right to inspect or audit another party's books/records; mere "
                 'recordkeeping or accounting duties do not establish that right.',
 'Termination For Convenience': 'Check a right to terminate without cause; termination only for '
                                'breach or insolvency is different. Retain party, notice and other '
                                'conditions.',
 'Most Favored Nation': "Check that another customer's more favorable terms entitle the "
                        'counterparty to comparable terms. A discount on its own is insufficient.',
 'Non-Compete': 'Identify whose competitive activity is restricted, in which market or territory '
                'and for how long. A description of competitors alone is insufficient.',
 'Exclusivity': 'Check a commitment to exclusive dealing, sole sourcing or exclusive supply or '
                'licensing. Identify the restricted party, products, territory and exceptions.',
 'No-Solicit Of Customers': 'Check a restriction on soliciting or doing business with the '
                            "counterparty's customers or partners. Distinguish solicitation of "
                            'employees.',
 'Competitive Restriction Exception': 'Link a specific exception to an applicable non-compete, '
                                      'exclusivity or customer non-solicitation restriction. An '
                                      'unrelated exception does not qualify.',
 'No-Solicit Of Employees': "Check restrictions on recruiting or hiring the counterparty's "
                            'employees or contractors. Identify exceptions such as general '
                            'advertisements.',
 'Non-Disparagement': 'Check a restriction on disparaging statements about the counterparty. '
                      'Confidentiality or restrictions on publishing a name alone are '
                      'insufficient.',
 'Rofr/Rofo/Rofn': 'Identify the right of first refusal, offer or negotiation, its holder, the '
                   'asset or opportunity and trigger. Ordinary purchase options alone are '
                   'insufficient.',
 'Change Of Control': 'Connect a merger, acquisition, sale of assets or similar change of control '
                      'to termination, notice or consent rights. Check assignment exceptions.',
 'Anti-Assignment': 'Check whether assignment to a third party is prohibited or requires consent '
                    'or notice, including permitted transfers. Distinguish assignment of IP '
                    'ownership.',
 'Revenue/Profit Sharing': 'Check a duty to share revenues or profits and identify the beneficiary '
                           'and calculation base. A fixed fee alone is insufficient.',
 'Price Restrictions': 'Identify an actual constraint on raising or lowering prices, including '
                       'conditions, timing or limits. A quoted price alone is insufficient.',
 'Minimum Commitment': 'Check a minimum purchase, spend, order or other minimum procurement '
                       'commitment to the counterparty, including units and measurement period.',
 'Volume Restriction': 'Check a usage limit or consequence for exceeding a volume threshold. '
                       'Minimum purchasing obligations address a different question.',
 'Ip Ownership Assignment': 'Check transfer or vesting of ownership of IP created by one party in '
                            'another. Mere permission to use IP or retention of existing ownership '
                            'is insufficient.',
 'Joint Ip Ownership': 'Check explicit shared ownership of intellectual property, identifying '
                       'owners and subject matter. Joint development alone does not establish '
                       'joint ownership.',
 'License Grant': 'Identify an operative grant of rights to use intellectual property or '
                  'technology from one contracting party to another. Mere access to products or '
                  'services, delivery of goods, or an expected future license without an actual IP '
                  'grant is insufficient.',
 'Non-Transferable License': 'First establish an operative intellectual-property license, then '
                             'check restrictions on transfer of that license. General restrictions '
                             'on assignment of the agreement alone do not prove a non-transferable '
                             'license.',
 'Affiliate License-Licensor': "Check whether a licensor's affiliate grants a license or the grant "
                               "includes IP of a licensor's affiliate. Distinguish those cases "
                               'from affiliates merely receiving rights.',
 'Affiliate License-Licensee': 'First establish an operative intellectual-property license, then '
                               'check whether the licensee affiliates receive rights under that '
                               'grant. Affiliate access to services alone is insufficient.',
 'Unlimited/All-You-Can-Eat-License': 'Check whether an enterprise-wide or unlimited usage license '
                                      'is granted, with its limits. Perpetual duration alone does '
                                      'not establish unlimited usage.',
 'Irrevocable Or Perpetual License': 'Check whether the granted license is irrevocable or '
                                     'perpetual, retaining termination or other conditions. '
                                     'Distinguish contract duration from license duration.',
 'Source Code Escrow': 'Check an obligation to deposit source code with a third-party escrow agent '
                       'and any release conditions. A data backup or ordinary source delivery is '
                       'insufficient.',
 'Post-Termination Services': 'Identify an affirmative obligation to provide services after '
                              'termination or expiry, such as transition assistance, continued '
                              'support, manufacturing or supply. Mere survival of confidentiality, '
                              'payment of accrued debts, return of property or destruction of '
                              'confidential information alone is insufficient.',
 'Uncapped Liability': 'Check explicit uncapped liability or a carve-out that removes an '
                       'applicable cap for a specified breach. A silent contract or damage '
                       'exclusion alone is insufficient.',
 'Cap On Liability': 'Identify the applicable monetary cap, formula or deadline to bring claims. '
                     'Retain parties and exclusions and distinguish uncapped carve-outs.',
 'Liquidated Damages': 'Identify predetermined damages or a termination fee and its trigger. '
                       'Ordinary service fees or indemnity alone are insufficient.',
 'Warranty Duration': 'Check whether the contract specifies a warranty period against defects or '
                      'errors, including starting events and conditions. The proposed Yes/No '
                      'describes existence of that provision, not a replacement duration.',
 'Covenant Not To Sue': 'Check a promise not to assert a claim or challenge ownership or validity '
                        'of intellectual property. A dispute forum or indemnity is insufficient.',
 'Third Party Beneficiary': 'Check whether an identified nonparty receives enforceable rights '
                            'under this contract. An express denial of third-party rights does not '
                            'support an affirmative answer.'}
