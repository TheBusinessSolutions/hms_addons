# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class InsuranceClaim(models.Model):
    _name = 'hms.insurance.claim'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acs.hms.mixin']
    _description = 'Claim'

    @api.depends('amount_requested', 'amount_pass')
    def _get_diff(self):
        for claim in self:
            claim.amount_difference = claim.amount_requested - claim.amount_pass

    @api.model
    def _default_insu_checklist(self):
        vals = []
        checklists = self.env['hms.insurance.checklist.template'].search([('active', '=', True)])
        for checklist in checklists:
            vals.append((0, 0, {
                'name': checklist.name,
            }))
        return vals
 
    @api.depends('checklist_ids')
    def _compute_checklist_ids_marked(self):
        for rec in self:
            done_checklist = rec.checklist_ids.filtered(lambda x: x.is_done)
            if len(rec.checklist_ids)>=1:
                rec.checklist_marked = (len(done_checklist)* 100)/len(rec.checklist_ids)

    name = fields.Char('Claim Number', required=True, default="/", tracking=True)
    patient_id = fields.Many2one('hms.patient', 'Patient', required=True, tracking=True)
    insurance_id = fields.Many2one('hms.patient.insurance', 'Insurance Policy', required=True, tracking=True)
    appointment_id = fields.Many2one('hms.appointment', 'Appointment')
    insurance_company_id = fields.Many2one('hms.insurance.company', related="insurance_id.insurance_company_id", string='Insurance Company', readonly=True, store=True)
    amount_requested = fields.Float('Total Claim Amount')
    amount_pass = fields.Float('Passed Amount')
    amount_received = fields.Float('Received Amount')
    amount_deductible = fields.Float('Deductible Amount')
    amount_difference = fields.Float(compute='_get_diff', string='Difference Amount')
    date = fields.Datetime(string='Claim Date', default=fields.Datetime.now)
    date_received = fields.Date('Claim Received Date')
    tpa_id = fields.Many2one('insurance.tpa', 'TPA')
    req_document_ids = fields.Many2many('hms.insurance.req.doc', 'hms_insurance_req_doc_rel', 'claim_id', 'doc_id', 'Required Documents')
    question = fields.Text('Question')
    answer = fields.Text('Answer')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
        ('sent', 'Sent For Approval'),
        ('approve', 'Approved'),
        ('received', 'Received'),
        ('cancel', 'Canceled'),
        ('done', 'Done')], 'Status', default='draft', tracking=True)
    doc_ids = fields.One2many(comodel_name='ir.attachment', inverse_name='claim_id', string='Document')
    checklist_ids = fields.One2many('hms.insurance.checklist', 'claim_id', string='Checklist', default=lambda self: self._default_insu_checklist())
    checklist_marked = fields.Float('Checklist Progress', compute='_compute_checklist_ids_marked',store=True)
    claim_for = fields.Selection([
        ('appointment', 'Appointment'),
        ('pharmacy', 'Pharmacy'),
        ('other', 'Other')], string='Claim Type', default='appointment')
    invoice_ids = fields.One2many('account.move', 'claim_id', string='Invoices')
    payment_ids = fields.One2many('account.payment', 'claim_id', string='Payments')
    company_id = fields.Many2one('res.company', 'Hospital', default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related='company_id.currency_id', string="Currency", readonly=True, required=True)
    total_invoice_amount = fields.Float(compute="_get_amounts", string="Total Invoices")
    total_payment_amount = fields.Float(compute="_get_amounts", string="Total Payments")
    prescription_id = fields.Many2one('prescription.order', 'Prescription')
    authorized_number = fields.Char('Authorization Number ID')

    def _get_amounts(self):
        for rec in self:
            rec.total_invoice_amount = sum(rec.invoice_ids.mapped('amount_total'))
            rec.total_payment_amount = sum(rec.payment_ids.mapped('amount'))

    def unlink(self):
        for data in self:
            if data.state in ['done']:
                raise UserError(('You can not delete record in done state'))
        return super(InsuranceClaim, self).unlink()

    def action_draft(self):
        self.state = 'draft'

    def action_confirm(self):
        if self.name=='/':
            self.name = self.env['ir.sequence'].next_by_code('hms.insurance.claim') or 'New Claim'
        self.state = 'confirm'

    def action_sent(self):
        self.state = 'sent'

    def action_approve(self):
        self.state = 'approve'

    def action_received(self):
        self.state = 'received'

    def action_done(self):
        self.date_received = fields.Date.today()
        self.state = 'done'

    def action_cancel(self):
        self.state = 'cancel'

    def action_view_invoice(self):
        invoices = self.env['account.move'].search([('claim_id', '=', self.id)])
        action = self.with_context(acs_open_blank_list=True).acs_action_view_invoice(invoices)
        partner_id = self.patient_id.partner_id.id
        if self.insurance_company_id and self.insurance_company_id.partner_id:
            partner_id = self.insurance_company_id.partner_id.id
        action['context'] = {
            'default_claim_id': self.id,
            'default_move_type': 'out_invoice',
            'default_patient_id': self.patient_id.id,
            'default_partner_id': partner_id}
        return action

    def get_relate_invoices(self):
        invoices = []
        if self.claim_for=='appointment':
            invoices = self.env['account.move'].search([('appointment_id', '=', self.appointment_id.id)])
        return invoices

    def action_view_record_invoice(self):
        invoices = self.get_relate_invoices()
        action = self.acs_action_view_invoice(invoices)
        partner_id = self.patient_id.partner_id.id
        if self.insurance_company_id and self.insurance_company_id.partner_id:
            partner_id = self.insurance_company_id.partner_id.id
        action['context'] = {
            'default_claim_id': self.id,
            'default_move_type': 'out_invoice',
            'default_patient_id': self.patient_id.id,
            'default_partner_id': partner_id}
        return action

    def action_payments(self):
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_account_payments_payable")
        action['domain'] = [('claim_id','=',self.id)]
        partner_id = self.patient_id.partner_id.id
        if self.insurance_company_id and self.insurance_company_id.partner_id:
            partner_id = self.insurance_company_id.partner_id.id
        action['context'] = {
            'default_claim_id': self.id,
            'default_payment_type': 'inbound',
            'default_partner_id': partner_id}
        return action
    
    def action_send_claim(self):
        '''
        This function opens a window to compose an email, with the template message loaded by default
        '''
        self.ensure_one()
        template_id = self.env['ir.model.data']._xmlid_to_res_id('acs_hms_insurance.acs_claim_email', raise_if_not_found=False)

        ctx = {
            'default_model': 'hms.insurance.claim',
            'default_res_ids': self.ids,
            'default_use_template': bool(template_id),
            'default_template_id': template_id,
            'default_composition_mode': 'comment',
            'force_email': True
        }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'views': [(False, 'form')],
            'view_id': False,
            'target': 'new',
            'context': ctx,
        }

