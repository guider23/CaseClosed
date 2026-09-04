# Dispute Defense Metrics

## Held-out Evaluation

- **Threshold**: `0.723`
- **Precision**: `0.684`
- **Recall**: `0.722`
- **F1 Score**: `0.000`

## Batch Recovery Simulation

Performance on the frozen held-out set simulating INR recovered.

| Strategy | INR Recovered | Auto-Response Rate |
|----------|---------------|--------------------|
| **Our System (AI)** | ₹18,946.30 | 76.0% |
| **Contest Everything** | ₹28,366.28 | 100% |
| **Contest Nothing** | ₹0.00 | 0% |

## Examples of Misclassifications

### disp_00115 (not_as_described)
- **Error Type**: Dropped but would have won (False Negative)
- **Amount**: ₹1,618.72
- **Model Prob**: 0.675
- **Actual Label**: merchant_won
- **Analysis**: The model scored this slightly below our 0.723 threshold. While the item was successfully delivered 9 days prior and the customer account is aged (229 days), there is absolutely no chat history (`chat_thread_exists: false`). For `not_as_described` claims, the model heavily penalizes the lack of customer chat interactions (where they might have previously admitted the product was fine). The model played it safe, but the merchant ended up winning anyway.

### disp_00119 (item_not_received)
- **Error Type**: Dropped but would have won (False Negative)
- **Amount**: ₹3,299.57
- **Model Prob**: 0.712
- **Actual Label**: merchant_won
- **Analysis**: This was agonizingly close to the threshold (0.712 vs 0.723). The merchant had ironclad evidence: Proof of Delivery and a verified Signature (`signature_flag: true`). However, the customer had a history of filing disputes (`customer_prior_disputes: 1`). The Gradient Boosting model learned that banks strongly favor buyers with a history of disputes, and severely discounted the score. The system dropped it, missing out on ₹3,299.

### disp_00002 (item_not_received)
- **Error Type**: Contested but lost (False Positive)
- **Amount**: ₹1,072.06
- **Model Prob**: 0.783
- **Actual Label**: merchant_lost
- **Analysis**: A costly False Positive. The model was highly confident (0.783) because the customer's account was ancient (1,177 days old) and the item was marked "delivered" with a POD. However, the model overlooked a critical weakness: `signature_flag: false`. In "Item Not Received" disputes, banks frequently rule against the merchant if there is no physical signature, regardless of the customer's trustworthiness. The model over-indexed on customer loyalty and lost the case (costing us the FP penalty).
