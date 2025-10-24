import React from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, List, ListItem,
  ListItemIcon, ListItemText, Chip, Paper, Divider, Container
} from '@mui/material';
import { Check, Star, ArrowForward } from '@mui/icons-material';
import { useTheme } from '../contexts/ThemeContext';

export default function TierComparison() {
  const { currentTheme } = useTheme();

  const tiers = [
    {
      name: 'Free',
      price: 0,
      credits: 10,
      billingPeriod: 'one-time',
      description: 'Perfect for testing and small projects',
      features: [
        'Auto OpenRouter account creation',
        '$10 free credits (one-time)',
        'Free models only',
        '$0.001/1k token markup',
        'Community support',
        'Basic usage analytics'
      ],
      limitations: [
        'No paid models',
        'Credits expire after 90 days'
      ],
      cta: 'Get Started',
      ctaHref: '/admin/subscription/plan',
      popular: false
    },
    {
      name: 'Starter',
      price: 30,
      credits: 30,
      billingPeriod: 'month',
      description: 'For individuals and small teams',
      features: [
        'Managed OpenRouter account',
        '$30 monthly credits',
        'Free + paid models',
        '10% markup on paid models',
        'Email support',
        'Advanced analytics',
        'Usage alerts'
      ],
      limitations: [],
      cta: 'Upgrade to Starter',
      ctaHref: '/admin/subscription/plan?tier=starter',
      popular: false
    },
    {
      name: 'Professional',
      price: 50,
      credits: 50,
      billingPeriod: 'month',
      description: 'Most popular for growing teams',
      features: [
        '$50 monthly credits OR BYOK',
        'Priority routing',
        '5% markup (credits) or 0% (BYOK)',
        'Team features (1-5 users)',
        'Priority email support',
        'Custom usage reports',
        'API key management',
        'Webhook integrations'
      ],
      limitations: [],
      cta: 'Upgrade to Pro',
      ctaHref: '/admin/subscription/plan?tier=professional',
      popular: true
    },
    {
      name: 'Enterprise',
      price: 99,
      credits: 100,
      billingPeriod: 'month',
      description: 'For large organizations',
      features: [
        '$100 monthly credits OR BYOK',
        'Dedicated routing',
        '0% markup on all models',
        'Unlimited team members',
        'White-label options',
        '24/7 dedicated support',
        'Custom SLA',
        'On-premise deployment option'
      ],
      limitations: [],
      cta: 'Contact Sales',
      ctaHref: 'mailto:sales@magicunicorn.tech',
      popular: false
    }
  ];

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ textAlign: 'center', mb: 6 }}>
        <Typography variant="h3" fontWeight={700} gutterBottom>
          Choose Your Plan
        </Typography>
        <Typography variant="h6" color="textSecondary">
          Simple, transparent pricing for every stage of your journey
        </Typography>
      </Box>

      {/* Pricing Cards */}
      <Grid container spacing={3} sx={{ mb: 6 }}>
        {tiers.map((tier) => (
          <Grid item xs={12} md={3} key={tier.name}>
            <Card
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                border: tier.popular ? '2px solid' : '1px solid',
                borderColor: tier.popular ? 'primary.main' : 'divider',
                background: tier.popular && currentTheme === 'magic-unicorn'
                  ? 'linear-gradient(135deg, rgba(139, 92, 246, 0.05) 0%, rgba(168, 85, 247, 0.05) 100%)'
                  : undefined,
                transition: 'all 0.3s ease',
                '&:hover': {
                  transform: 'translateY(-8px)',
                  boxShadow: 6
                }
              }}
            >
              {tier.popular && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: -12,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    zIndex: 1
                  }}
                >
                  <Chip
                    label="Most Popular"
                    color="primary"
                    icon={<Star />}
                    sx={{ fontWeight: 600 }}
                  />
                </Box>
              )}

              <CardContent sx={{ flexGrow: 1, pt: tier.popular ? 4 : 3 }}>
                {/* Tier Name */}
                <Typography variant="h5" fontWeight={600} gutterBottom>
                  {tier.name}
                </Typography>

                {/* Price */}
                <Box sx={{ mb: 2 }}>
                  <Typography variant="h3" fontWeight={700} component="span">
                    ${tier.price}
                  </Typography>
                  <Typography variant="body1" color="textSecondary" component="span">
                    /{tier.billingPeriod}
                  </Typography>
                </Box>

                {/* Credits Badge */}
                <Chip
                  label={`${tier.credits === 10 ? '$10 free' : `$${tier.credits}`} in credits`}
                  color={tier.popular ? 'primary' : 'default'}
                  variant="outlined"
                  sx={{ mb: 2 }}
                />

                {/* Description */}
                <Typography variant="body2" color="textSecondary" sx={{ mb: 3, minHeight: 40 }}>
                  {tier.description}
                </Typography>

                <Divider sx={{ mb: 2 }} />

                {/* Features */}
                <List dense>
                  {tier.features.map((feature, idx) => (
                    <ListItem key={idx} disableGutters>
                      <ListItemIcon sx={{ minWidth: 32 }}>
                        <Check color="success" fontSize="small" />
                      </ListItemIcon>
                      <ListItemText
                        primary={feature}
                        primaryTypographyProps={{ variant: 'body2' }}
                      />
                    </ListItem>
                  ))}
                </List>

                {/* Limitations */}
                {tier.limitations.length > 0 && (
                  <>
                    <Divider sx={{ my: 2 }} />
                    <Typography variant="caption" color="textSecondary" display="block" gutterBottom>
                      Limitations:
                    </Typography>
                    {tier.limitations.map((limitation, idx) => (
                      <Typography key={idx} variant="caption" color="error" display="block">
                        • {limitation}
                      </Typography>
                    ))}
                  </>
                )}

                {/* CTA Button */}
                <Button
                  variant={tier.popular ? 'contained' : 'outlined'}
                  fullWidth
                  size="large"
                  endIcon={<ArrowForward />}
                  href={tier.ctaHref}
                  sx={{ mt: 3 }}
                >
                  {tier.cta}
                </Button>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Feature Comparison Table */}
      <Paper sx={{ p: 3, mb: 4 }}>
        <Typography variant="h5" fontWeight={600} gutterBottom>
          Feature Comparison
        </Typography>
        <Box sx={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', padding: '12px', borderBottom: '2px solid #e0e0e0' }}>
                  <Typography variant="body2" fontWeight={600}>Feature</Typography>
                </th>
                {tiers.map(tier => (
                  <th key={tier.name} style={{ textAlign: 'center', padding: '12px', borderBottom: '2px solid #e0e0e0' }}>
                    <Typography variant="body2" fontWeight={600}>{tier.name}</Typography>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <ComparisonRow feature="Monthly Credits" values={['$10 (one-time)', '$30', '$50', '$100']} />
              <ComparisonRow feature="Free Models" values={[true, true, true, true]} />
              <ComparisonRow feature="Paid Models" values={[false, true, true, true]} />
              <ComparisonRow feature="BYOK Support" values={[false, false, true, true]} />
              <ComparisonRow feature="Team Members" values={['1', '1', '1-5', 'Unlimited']} />
              <ComparisonRow feature="Markup Rate" values={['$0.001/1k', '10%', '5% / 0%', '0%']} />
              <ComparisonRow feature="Support" values={['Community', 'Email', 'Priority', '24/7 Dedicated']} />
              <ComparisonRow feature="Custom Reports" values={[false, false, true, true]} />
              <ComparisonRow feature="API Keys" values={['1', '3', '10', 'Unlimited']} />
              <ComparisonRow feature="Webhooks" values={[false, false, true, true]} />
              <ComparisonRow feature="White-label" values={[false, false, false, true]} />
              <ComparisonRow feature="SLA" values={[false, false, false, 'Custom']} />
            </tbody>
          </table>
        </Box>
      </Paper>

      {/* FAQ Section */}
      <Box>
        <Typography variant="h5" fontWeight={600} gutterBottom>
          Frequently Asked Questions
        </Typography>
        <Grid container spacing={3}>
          <Grid item xs={12} md={6}>
            <FAQItem
              question="What are credits?"
              answer="Credits are the currency used for AI model usage. Each API call deducts credits based on the model used and tokens processed."
            />
            <FAQItem
              question="What is BYOK?"
              answer="Bring Your Own Key (BYOK) allows you to use your own API keys from providers like OpenAI, Anthropic, etc. with 0% markup."
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <FAQItem
              question="Can I switch plans?"
              answer="Yes! You can upgrade or downgrade at any time. Changes take effect at the start of your next billing cycle."
            />
            <FAQItem
              question="What happens if I run out of credits?"
              answer="Your services will be paused until you add more credits or upgrade your plan. We'll send warnings when you reach 75% and 90% usage."
            />
          </Grid>
        </Grid>
      </Box>
    </Container>
  );
}

// Helper component for comparison table rows
function ComparisonRow({ feature, values }) {
  return (
    <tr style={{ borderBottom: '1px solid #e0e0e0' }}>
      <td style={{ padding: '12px' }}>
        <Typography variant="body2">{feature}</Typography>
      </td>
      {values.map((value, idx) => (
        <td key={idx} style={{ textAlign: 'center', padding: '12px' }}>
          {typeof value === 'boolean' ? (
            value ? <Check color="success" /> : <Typography variant="body2" color="textSecondary">-</Typography>
          ) : (
            <Typography variant="body2">{value}</Typography>
          )}
        </td>
      ))}
    </tr>
  );
}

// Helper component for FAQ items
function FAQItem({ question, answer }) {
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} gutterBottom>
        {question}
      </Typography>
      <Typography variant="body2" color="textSecondary">
        {answer}
      </Typography>
    </Box>
  );
}
