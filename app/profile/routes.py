from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.profile import profile
from app.profile.forms import ProfileForm, INTERESTS
from app.extensions import db


@profile.route('/profile')
@login_required
def view():
    return render_template('profile/view.html')


@profile.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit():
    form = ProfileForm(obj=current_user)

    if form.validate_on_submit():
        current_user.name         = form.name.data.strip()
        current_user.bio          = form.bio.data.strip()
        current_user.travel_style = form.travel_style.data
        current_user.phone        = form.phone.data.strip() if form.phone.data else ''

        selected = request.form.getlist('interests')
        valid    = [i for i in selected if i in INTERESTS]
        current_user.interests = ','.join(valid[:3])  # cap at 3

        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('profile.view'))

    # Pre-tick checkboxes on GET
    selected_interests = current_user.interests_list()
    return render_template('profile/edit.html',
                           form=form,
                           all_interests=INTERESTS,
                           selected_interests=selected_interests)
